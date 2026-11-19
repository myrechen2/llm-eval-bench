import csv
import json
import math
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


def load_deploys():
    with open(DATA_DIR / "deploys.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def analyze_orders_and_charges(deploys):
    orders = {}
    with open(DATA_DIR / "orders.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["amount_minor"] = int(row["amount_minor"])
            row["created_dt"] = parse_utc(row["created_at_utc"])
            orders[row["order_id"]] = row

    print(f"Total orders: {len(orders)}")
    print("Order statuses:", Counter(o["status"] for o in orders.values()))
    print("Order currencies:", Counter(o["currency"] for o in orders.values()))
    print("Order payment_methods:", Counter(o["payment_method"] for o in orders.values()))

    charges_by_order = defaultdict(list)
    all_charges = []
    with open(DATA_DIR / "provider_charges.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["amount_minor"] = int(row["amount_minor"])
            row["created_dt"] = parse_utc(row["created_at_utc"])
            all_charges.append(row)
            charges_by_order[row["order_id"]].append(row)

    print(f"Total charges: {len(all_charges)}")
    print("Charge statuses:", Counter(c["status"] for c in all_charges))
    print("Charge currencies:", Counter(c["currency"] for c in all_charges))

    orphan_orders = set(charges_by_order.keys()) - set(orders.keys())
    print("Orphan charge order_ids:", orphan_orders)

    # Check currency mismatches between order and charges
    mismatched = []
    for oid, clist in charges_by_order.items():
        oc = orders[oid]["currency"]
        for c in clist:
            if c["currency"] != oc:
                mismatched.append((oid, oc, c))
    print("Currency mismatches:", mismatched)

    # Check extra charges and outstanding refund
    extra_charges = []
    outstanding_by_currency = Counter()
    orders_needing_refund = 0
    user_outstanding_cny = defaultdict(int)
    user_outstanding_raw = defaultdict(lambda: Counter())

    for oid, order in orders.items():
        owed = order["amount_minor"] if order["status"] == "paid" else 0
        clist = sorted(charges_by_order.get(oid, []), key=lambda c: (c["created_dt"], c["charge_id"]))

        # Running total of successful charges (succeeded or refunded)
        running = 0
        for c in clist:
            if c["status"] in ("succeeded", "refunded"):
                prev = running
                running += c["amount_minor"]
                if running > owed:
                    extra_charges.append((c, order, prev, running, owed))

        # Outstanding refund = sum(status == succeeded) - owed, floored at 0
        succeeded_sum = sum(c["amount_minor"] for c in clist if c["status"] == "succeeded")
        out_ref = max(0, succeeded_sum - owed)
        if out_ref > 0:
            orders_needing_refund += 1
            cur = order["currency"]
            outstanding_by_currency[cur] += out_ref
            user_outstanding_raw[order["user_id"]][cur] += out_ref

    print(f"\nTotal extra charges (across all time): {len(extra_charges)}")
    extra_charges.sort(key=lambda x: x[0]["created_dt"])
    print("First 10 extra charges:")
    for c, o, prev, run, owed in extra_charges[:10]:
        print(
            f"  {c['created_at_utc']} charge={c['charge_id']} order={o['order_id']} "
            f"user={o['user_id']} o_status={o['status']} c_status={c['status']} "
            f"amt={c['amount_minor']} {c['currency']} prev={prev} run={run} owed={owed} idem={c['idempotency_key']}"
        )
    print("Last 10 extra charges:")
    for c, o, prev, run, owed in extra_charges[-10:]:
        print(
            f"  {c['created_at_utc']} charge={c['charge_id']} order={o['order_id']} "
            f"user={o['user_id']} o_status={o['status']} c_status={c['status']} "
            f"amt={c['amount_minor']} {c['currency']} prev={prev} run={run} owed={owed} idem={c['idempotency_key']}"
        )

    print(f"\norders_needing_refund: {orders_needing_refund}")
    print(f"outstanding_refund_minor: {dict(outstanding_by_currency)}")

    # Top users in CNY minor (1 USD = 7.10 CNY)
    user_totals = []
    for uid, cur_map in user_outstanding_raw.items():
        cny_equiv = cur_map["CNY"] + cur_map["USD"] * 7.10
        user_totals.append((cny_equiv, round(cny_equiv), uid, dict(cur_map)))
    user_totals.sort(reverse=True)
    print("Top 10 users by outstanding CNY minor:")
    for exact, rounded, uid, cur_map in user_totals[:10]:
        print(f"  {uid}: exact={exact} rounded={rounded} breakdown={cur_map}")

    # Check if any orders have extra charges BEFORE culprit or AFTER mitigation
    print("\nDeploys:")
    for d in deploys:
        print(f"  {d['deploy_id']} {d['service']} {d['version']} {d['started_at_utc']} -> {d['finished_at_utc']} | {d['summary']}")

    return orders, charges_by_order, extra_charges


def analyze_logs(deploys, extra_charges):
    # Inspect payment-svc.log events and versions
    p_versions = Counter()
    p_events = Counter()
    p_results = Counter()
    p_other_lines = []
    # Sample lines around deploy times
    sample_events_non_standard = []
    charge_results_by_ver = defaultdict(Counter)
    charge_result_rows = []

    kv_re = re.compile(r"(\w+)=(\S+)")
    line_re = re.compile(r"^(\S+)\s+(\w+)\s+\[payment-svc\s+(\S+)\]\s+(.*)$")

    with open(DATA_DIR / "logs/payment-svc.log", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.rstrip("\r\n")
            m = line_re.match(line)
            if not m:
                p_other_lines.append((idx, line))
                continue
            ts_str, level, ver, rest = m.groups()
            p_versions[ver] += 1
            kvs = dict(kv_re.findall(rest))
            ev = kvs.get("event", "<none>")
            p_events[ev] += 1
            if ev not in ("charge.request", "charge.result"):
                if len(sample_events_non_standard) < 20:
                    sample_events_non_standard.append((ts_str, ver, line))
            if ev == "charge.result":
                res = kvs.get("result")
                p_results[res] += 1
                charge_results_by_ver[ver][res] += 1
                charge_result_rows.append((parse_utc(ts_str), ver, res, int(kvs["duration_ms"]), kvs, line))

    print("\n--- payment-svc.log ---")
    print("Unmatched lines:", len(p_other_lines), p_other_lines[:5])
    print("Versions:", p_versions)
    print("Events:", p_events)
    print("Results:", p_results)
    print("Results by version:", {k: dict(v) for k, v in charge_results_by_ver.items()})
    print("Sample non-standard events:")
    for ts, ver, l in sample_events_non_standard:
        print(" ", l)

    # Check gateway-access.log
    gw_re = re.compile(
        r'^(\S+) - (\S+) \[(\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2})\] "(\S+) (\S+) ([^"]+)" (\d+) rt=(\S+) upstream=(\S+) trace=(\S+)$'
    )
    gw_unmatched = []
    gw_statuses = Counter()
    gw_paths = Counter()
    gw_502_checkouts = []
    min_gw_ts = None
    max_gw_ts = None

    with open(DATA_DIR / "logs/gateway-access.log", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.rstrip("\r\n")
            m = gw_re.match(line)
            if not m:
                gw_unmatched.append((idx, line))
                continue
            ip, uid, dt_str, method, path, proto, status_str, rt, upstream, trace = m.groups()
            dt_cst = datetime.strptime(dt_str, "%d/%b/%Y:%H:%M:%S").replace(tzinfo=CST)
            dt_utc = dt_cst.astimezone(timezone.utc)
            if min_gw_ts is None or dt_utc < min_gw_ts:
                min_gw_ts = dt_utc
            if max_gw_ts is None or dt_utc > max_gw_ts:
                max_gw_ts = dt_utc
            status = int(status_str)
            gw_statuses[status] += 1
            if method == "POST" and path == "/api/v2/checkout" and status == 502:
                gw_502_checkouts.append((dt_utc, dt_str, trace, rt, line))

    print("\n--- gateway-access.log ---")
    print("Unmatched lines:", len(gw_unmatched), gw_unmatched[:5])
    print("Time range UTC:", min_gw_ts, "->", max_gw_ts)
    print("Statuses:", gw_statuses)
    print("Total POST /api/v2/checkout 502:", len(gw_502_checkouts))

    # Inspect order-svc.jsonl events and versions
    o_events = Counter()
    o_vers = Counter()
    with open(DATA_DIR / "logs/order-svc.jsonl", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            o_events[obj.get("event")] += 1
            o_vers[obj.get("ver")] += 1
    print("\n--- order-svc.jsonl ---")
    print("Versions:", o_vers)
    print("Events:", o_events)

    return charge_result_rows, gw_502_checkouts


def main():
    deploys = load_deploys()
    orders, charges_by_order, extra_charges = analyze_orders_and_charges(deploys)
    charge_result_rows, gw_502_checkouts = analyze_logs(deploys, extra_charges)

    # Check culprit and mitigation windows
    dep_map = {d["deploy_id"]: d for d in deploys}
    culprit = parse_utc(dep_map["DEP-7731"]["finished_at_utc"])
    mitigation = parse_utc(dep_map["DEP-7740"]["finished_at_utc"])
    before_start = culprit - timedelta(hours=2)

    print(f"\nAssuming culprit=DEP-7731 ({culprit.isoformat()}) and mitigation=DEP-7740 ({mitigation.isoformat()}):")
    extra_before = [x for x in extra_charges if x[0]["created_dt"] < culprit]
    extra_during = [x for x in extra_charges if culprit <= x[0]["created_dt"] < mitigation]
    extra_after = [x for x in extra_charges if x[0]["created_dt"] >= mitigation]
    print(f"Extra charges: before={len(extra_before)}, during={len(extra_during)}, after={len(extra_after)}")
    if extra_before:
        print("  Extra before:", [(x[0]["created_at_utc"], x[0]["order_id"]) for x in extra_before[:5]])
    if extra_after:
        print("  Extra after:", [(x[0]["created_at_utc"], x[0]["order_id"]) for x in extra_after[:5]])

    gw_in_win = [x for x in gw_502_checkouts if culprit <= x[0] < mitigation]
    print(f"gateway_checkout_502_in_window: {len(gw_in_win)}")

    before_dur = sorted(r[3] for r in charge_result_rows if before_start <= r[0] < culprit)
    during_rows = [r for r in charge_result_rows if culprit <= r[0] < mitigation]
    during_dur = sorted(r[3] for r in during_rows)
    during_timeouts = sum(1 for r in during_rows if r[2] == "timeout")

    def p95(sorted_vals):
        n = len(sorted_vals)
        idx = math.ceil(0.95 * n) - 1
        return sorted_vals[idx]

    print(f"before count={len(before_dur)}, p95={p95(before_dur)}")
    print(f"during count={len(during_dur)}, p95={p95(during_dur)}, timeouts={during_timeouts}, rate={during_timeouts*100/len(during_rows):.4f}%")


if __name__ == "__main__":
    main()
