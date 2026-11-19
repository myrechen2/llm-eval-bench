import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path("tasks/02-log-forensics/data")
CST = timezone(timedelta(hours=8))


def parse_utc(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def main():
    orders = {}
    with open(DATA_DIR / "orders.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["amount_minor"] = int(r["amount_minor"])
            orders[r["order_id"]] = r

    charges_by_order = defaultdict(list)
    with open(DATA_DIR / "provider_charges.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["amount_minor"] = int(r["amount_minor"])
            charges_by_order[r["order_id"]].append(r)

    # 1. Inspect O0314-001701, O0314-004083, O0314-003221, O0314-004068, and U100670 orders
    target_orders = {"O0314-001701", "O0314-004083", "O0314-003221", "O0314-004068"}
    for oid, o in orders.items():
        if o["user_id"] == "U100670":
            target_orders.add(oid)

    print("=== TARGET ORDERS & CHARGES ===")
    for oid in sorted(target_orders):
        print("ORDER:", orders[oid])
        for c in charges_by_order[oid]:
            print("  CHARGE:", c)

    # 2. Scan payment-svc.log for config.loaded, sample charge.status_check, sample charge.retry, sample refund.result, and target_orders
    print("\n=== PAYMENT-SVC DETAILS ===")
    status_checks = []
    retries = []
    refunds = []
    config_lines = []
    target_pay_lines = defaultdict(list)
    boundary_pay_lines = []
    ver_windows = defaultdict(list)

    kv_re = re.compile(r"(\w+)=(\S+)")
    line_re = re.compile(r"^(\S+)\s+(\w+)\s+\[payment-svc\s+(\S+)\]\s+(.*)$")

    t_culprit = parse_utc("2026-03-14T06:40:00Z")
    t_mitigation = parse_utc("2026-03-14T08:02:30Z")
    t_before = parse_utc("2026-03-14T04:40:00Z")

    with open(DATA_DIR / "logs/payment-svc.log", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            m = line_re.match(line)
            if not m:
                continue
            ts_str, level, ver, rest = m.groups()
            dt = parse_utc(ts_str)
            kvs = dict(kv_re.findall(rest))
            ev = kvs.get("event")
            ver_windows[ver].append(dt)
            if ev == "config.loaded":
                config_lines.append(line)
            elif ev == "charge.status_check" and len(status_checks) < 10:
                status_checks.append(line)
            elif ev == "charge.retry" and len(retries) < 10:
                retries.append(line)
            elif ev == "refund.result" and len(refunds) < 5:
                refunds.append(line)
            if kvs.get("order") in target_orders:
                target_pay_lines[kvs["order"]].append(line)
            if ev == "charge.result":
                for bound in (t_before, t_culprit, t_mitigation):
                    if abs((dt - bound).total_seconds()) <= 5:
                        boundary_pay_lines.append(line)

    print("config.loaded:")
    for l in config_lines:
        print(" ", l)
    print("Version time spans:")
    for v, dts in ver_windows.items():
        print(f"  {v}: {min(dts).isoformat()} -> {max(dts).isoformat()} (count={len(dts)})")
    print("Sample charge.status_check:")
    for l in status_checks[:5]:
        print(" ", l)
    print("Sample charge.retry:")
    for l in retries[:5]:
        print(" ", l)
    print("Sample refund.result:")
    for l in refunds[:5]:
        print(" ", l)
    print("Target order payment-svc lines:")
    for oid in sorted(target_pay_lines):
        print(f"  [{oid}]")
        for l in target_pay_lines[oid]:
            print("   ", l)
    print("charge.result lines within 5s of boundaries:")
    for l in boundary_pay_lines:
        print(" ", l)

    # 3. Scan order-svc.jsonl for target_orders and cache.warmup_miss / order.payment_failed stats
    print("\n=== ORDER-SVC DETAILS ===")
    warmup_lines = []
    target_order_logs = defaultdict(list)
    trace_to_order = {}
    with open(DATA_DIR / "logs/order-svc.jsonl", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            oid = obj.get("order_id")
            if obj.get("trace_id") and oid:
                trace_to_order[obj["trace_id"]] = oid
            if oid in target_orders:
                target_order_logs[oid].append(line.strip())
            if obj.get("event") == "cache.warmup_miss" and len(warmup_lines) < 5:
                warmup_lines.append(line.strip())
    for l in warmup_lines:
        print(" warmup:", l)
    for oid in sorted(target_order_logs):
        print(f"  [{oid}]")
        for l in target_order_logs[oid]:
            print("   ", l)

    # 4. Inspect gateway-access.log 502s by path and time, and around boundaries
    print("\n=== GATEWAY 502 BREAKDOWN ===")
    gw_re = re.compile(
        r'^(\S+) - (\S+) \[(\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2})\] "(\S+) (\S+) ([^"]+)" (\d+) rt=(\S+) upstream=(\S+) trace=(\S+)$'
    )
    gw502_by_path = Counter()
    gw502_checkout_outside = []
    gw502_checkout_boundary = []
    gw_target_traces = []
    target_traces = set(trace_to_order[oid] for oid in [] )  # build reverse
    order_to_traces = defaultdict(set)
    for tr, oid in trace_to_order.items():
        if oid in target_orders:
            order_to_traces[oid].add(tr)
    all_target_traces = set().union(*order_to_traces.values()) if order_to_traces else set()

    with open(DATA_DIR / "logs/gateway-access.log", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            m = gw_re.match(line)
            if not m:
                continue
            ip, uid, dt_str, method, path, proto, status_str, rt, upstream, trace = m.groups()
            status = int(status_str)
            dt_utc = datetime.strptime(dt_str, "%d/%b/%Y:%H:%M:%S").replace(tzinfo=CST).astimezone(timezone.utc)
            if trace in all_target_traces:
                gw_target_traces.append((dt_utc.isoformat(), line))
            if status == 502:
                gw502_by_path[(method, path, upstream)] += 1
                if method == "POST" and path == "/api/v2/checkout":
                    if abs((dt_utc - t_culprit).total_seconds()) <= 60 or abs((dt_utc - t_mitigation).total_seconds()) <= 60:
                        gw502_checkout_boundary.append((dt_utc.isoformat(), trace_to_order.get(trace), line))
                    if not (t_culprit <= dt_utc < t_mitigation):
                        gw502_checkout_outside.append((dt_utc.isoformat(), trace_to_order.get(trace), line))

    print("502 by (method, path, upstream):", gw502_by_path)
    print("Target order gateway lines:")
    for item in gw_target_traces:
        print(" ", item)
    print("POST /api/v2/checkout 502 near boundaries (+/-60s):")
    for item in gw502_checkout_boundary:
        print(" ", item)
    print(f"POST /api/v2/checkout 502 outside [06:40:00Z, 08:02:30Z): count={len(gw502_checkout_outside)}")
    for item in gw502_checkout_outside[:15]:
        print(" ", item)


if __name__ == "__main__":
    main()
