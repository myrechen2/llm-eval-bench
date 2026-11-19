"""Deep verification and evidence extraction for Task 02."""
from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[4] / "tasks" / "02-log-forensics" / "data"
CST = timezone(timedelta(hours=8))
UTC = timezone.utc


def parse_utc(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(UTC)


def parse_gateway_ts(s: str) -> datetime:
    return datetime.strptime(s, "%d/%b/%Y:%H:%M:%S").replace(tzinfo=CST).astimezone(UTC)


def main() -> None:
    orders = {}
    with (DATA_DIR / "orders.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["amount_minor"] = int(r["amount_minor"])
            orders[r["order_id"]] = r

    charges_by_order = defaultdict(list)
    with (DATA_DIR / "provider_charges.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["amount_minor"] = int(r["amount_minor"])
            r["created_dt"] = parse_utc(r["created_at_utc"])
            charges_by_order[r["order_id"]].append(r)

    # 1. Inspect specific orders: O0314-001701, O0314-003214, O0314-003220, O0314-003221, O0314-003222, O0314-004083, and top user U100670
    target_orders = {"O0314-001701", "O0314-003214", "O0314-003220", "O0314-003221", "O0314-003222", "O0314-004083"}
    top_user_orders = {oid for oid, o in orders.items() if o["user_id"] == "U100670"}
    print("=== Top user U100670 orders ===")
    for oid in sorted(top_user_orders):
        o = orders[oid]
        cs = sorted(charges_by_order[oid], key=lambda c: c["created_at_utc"])
        print(" ", o)
        for c in cs:
            print("    charge:", c["charge_id"], c["status"], c["amount_minor"], c["currency"], c["created_at_utc"], c["idempotency_key"])

    print("\n=== Target orders charges ===")
    for oid in sorted(target_orders):
        print("Order:", orders[oid])
        for c in sorted(charges_by_order[oid], key=lambda c: c["created_at_utc"]):
            print("  charge:", c["charge_id"], c["status"], c["amount_minor"], c["currency"], c["created_at_utc"], c["idempotency_key"], "refunded_at=", c["refunded_at_utc"])

    # 2. Check all split orders
    split_over = 0
    for oid, o in orders.items():
        if o["payment_method"] == "split":
            cs = charges_by_order[oid]
            owed = o["amount_minor"] if o["status"] == "paid" else 0
            s_all = sum(c["amount_minor"] for c in cs if c["status"] in ("succeeded", "refunded"))
            if s_all != owed:
                split_over += 1
                print("Split mismatch:", oid, o["status"], owed, s_all, [(c["status"], c["amount_minor"], c["idempotency_key"]) for c in cs])
    print("Split orders with sum(succ+ref) != owed:", split_over)

    # 3. Check ALL charges around 06:39:00Z - 06:42:00Z for orders with >1 charge or payment_failed
    print("\n=== Orders with extra charges near 06:40:00Z ===")
    for oid, o in orders.items():
        owed = o["amount_minor"] if o["status"] == "paid" else 0
        cs = [c for c in charges_by_order[oid] if c["status"] in ("succeeded", "refunded")]
        if sum(c["amount_minor"] for c in cs) > owed:
            cs.sort(key=lambda c: c["created_dt"])
            if cs[0]["created_dt"] <= parse_utc("2026-03-14T06:42:00Z"):
                print(f"  {oid} ({o['status']}, owed={owed}):", [(c["created_at_utc"], c["status"], c["amount_minor"], c["charge_id"]) for c in cs])

    # 4. Check payment-svc logs for target_orders and also check v2.13.4 attempt=2 and v2.14.2 retries
    print("\n=== payment-svc logs for target orders & v2.13.4 attempt=2 ===")
    with (DATA_DIR / "logs" / "payment-svc.log").open(encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            for oid in ("O0314-001701", "O0314-003214", "O0314-003220", "O0314-003221", "O0314-003222", "O0314-004083"):
                if f"order={oid} " in line:
                    print(f"  L{ln}: {line.strip()}")
            if "[payment-svc v2.13.4]" in line and "attempt=2" in line:
                print(f"  [v2.13.4 attempt=2] L{ln}: {line.strip()}")

    # 5. Check gateway paths containing 'checkout' and 502 distribution by 10-min UTC bucket
    gw_re = re.compile(
        r'^(\S+) - (\S+) \[([^\]]+)\] "(\S+) (\S+) HTTP/[^"]+" (\d+) rt=([\d.]+) upstream=(\S+) trace=(\S+)$'
    )
    checkout_paths = Counter()
    gw_502_buckets = Counter()
    with (DATA_DIR / "logs" / "gateway-access.log").open(encoding="utf-8") as f:
        for line in f:
            m = gw_re.match(line.rstrip("\n"))
            assert m
            ip, uid, ts_str, method, path, status_s, rt_s, upstream, trace = m.groups()
            if "checkout" in path:
                checkout_paths[(method, path)] += 1
            if method == "POST" and path == "/api/v2/checkout" and status_s == "502":
                dt = parse_gateway_ts(ts_str)
                b = dt.replace(minute=(dt.minute // 10) * 10, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M")
                gw_502_buckets[b] += 1
    print("\nCheckout paths in gateway:", dict(checkout_paths))
    print("POST /api/v2/checkout 502 by 10-min UTC bucket:")
    for k in sorted(gw_502_buckets):
        print(f"  {k}Z: {gw_502_buckets[k]}")

    # 6. Check payment-svc charge.result boundary timestamps and p95 verification
    c_end = parse_utc("2026-03-14T06:40:00Z")
    b_start = c_end - timedelta(hours=2)
    m_end = parse_utc("2026-03-14T08:02:30Z")
    pay_re = re.compile(r"^(\S+)\s+(\S+)\s+\[payment-svc\s+(\S+)\]\s+(.*)$")
    boundary_pay = []
    before_durs = []
    during_durs = []
    during_to = 0
    with (DATA_DIR / "logs" / "payment-svc.log").open(encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            m = pay_re.match(line.rstrip("\n"))
            ts_s, level, ver, rest = m.groups()
            kv = dict(tok.split("=", 1) for tok in rest.split() if "=" in tok)
            if kv.get("event") != "charge.result":
                continue
            dt = parse_utc(ts_s)
            for bname, bdt in [("b_start", b_start), ("c_end", c_end), ("m_end", m_end)]:
                if abs((dt - bdt).total_seconds()) <= 5:
                    boundary_pay.append((bname, ts_s, ver, kv.get("order"), kv.get("result"), kv.get("duration_ms")))
            dur = int(kv["duration_ms"])
            if b_start <= dt < c_end:
                before_durs.append(dur)
            elif c_end <= dt < m_end:
                during_durs.append(dur)
                if kv["result"] == "timeout":
                    during_to += 1

    print("\nPayment charge.result near window boundaries (+/- 5s):")
    for row in boundary_pay:
        print(" ", row)
    before_durs.sort()
    during_durs.sort()
    b_idx = math.ceil(0.95 * len(before_durs)) - 1
    d_idx = math.ceil(0.95 * len(during_durs)) - 1
    print(f"before n={len(before_durs)}, ceil(0.95*n)={b_idx+1}, vals around p95: {before_durs[b_idx-2:b_idx+3]}")
    print(f"during n={len(during_durs)}, ceil(0.95*n)={d_idx+1}, vals around p95: {during_durs[d_idx-2:d_idx+3]}")
    print(f"during timeouts={during_to}/{len(during_durs)} = {during_to/len(during_durs)*100:.6f}%")

    # 7. Check order-svc logs for O0314-003220, O0314-003221, O0314-003222, O0314-001701, and gateway logs for their traces
    traces = {}
    print("\n=== order-svc logs for sample orders ===")
    with (DATA_DIR / "logs" / "order-svc.jsonl").open(encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            obj = json.loads(line)
            if obj.get("order_id") in ("O0314-001701", "O0314-003214", "O0314-003220", "O0314-003221", "O0314-003222", "O0314-004083"):
                print(f"  L{ln}: {line.strip()}")
                if "trace_id" in obj:
                    traces[obj["trace_id"]] = obj["order_id"]

    print("\n=== gateway logs for those traces ===")
    with (DATA_DIR / "logs" / "gateway-access.log").open(encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            for tr, oid in traces.items():
                if f"trace={tr}" in line:
                    print(f"  [{oid}] L{ln}: {line.strip()}")

    # 8. Check order-svc v3.9.0 rollout (DEP-7735) and gateway cfg-0314a (DEP-7729)
    # Count extra charges before and after DEP-7735 (07:12:40Z)
    ec_before_7735 = 0
    ec_after_7735 = 0
    t_7735 = parse_utc("2026-03-14T07:12:40Z")
    for oid, o in orders.items():
        owed = o["amount_minor"] if o["status"] == "paid" else 0
        cs = sorted([c for c in charges_by_order[oid] if c["status"] in ("succeeded", "refunded")], key=lambda c: c["created_dt"])
        running = 0
        for c in cs:
            running += c["amount_minor"]
            if running > owed and c["created_dt"] >= c_end:
                if c["created_dt"] < t_7735:
                    ec_before_7735 += 1
                else:
                    ec_after_7735 += 1
    print(f"\nExtra charges during incident: before DEP-7735={ec_before_7735}, after DEP-7735={ec_after_7735}")

    # Check v2.14.2 retries (if any) and v2.13.4 status_check counts during PayNova slowness (06:30Z - 08:31Z)
    v134_sc = Counter()
    v142_to = 0
    with (DATA_DIR / "logs" / "payment-svc.log").open(encoding="utf-8") as f:
        for line in f:
            if "[payment-svc v2.13.4]" in line and "event=charge.status_check" in line:
                if "found=true" in line:
                    v134_sc["found=true"] += 1
                else:
                    v134_sc["found=false"] += 1
            if "[payment-svc v2.14.2]" in line and "result=timeout" in line:
                v142_to += 1
    print("v2.13.4 status_check results:", dict(v134_sc), "v2.14.2 timeouts:", v142_to)


if __name__ == "__main__":
    main()
