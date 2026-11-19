import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path("tasks/02-log-forensics/data")
CST = timezone(timedelta(hours=8))


def parse_utc(ts: str) -> datetime:
    # Handle both '2026-03-14T06:40:00Z' and '...123Z'
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def parse_gw_cst(ts: str) -> datetime:
    # Format: 14/Mar/2026:06:00:00 (Asia/Shanghai UTC+8)
    dt = datetime.strptime(ts, "%d/%b/%Y:%H:%M:%S")
    return dt.replace(tzinfo=CST).astimezone(timezone.utc)


def main() -> None:
    # 1. Load deploys
    with (DATA_DIR / "deploys.csv").open(encoding="utf-8") as f:
        deploys = {row["deploy_id"]: row for row in csv.DictReader(f)}

    # 2. Load orders
    orders = {}
    order_statuses = Counter()
    order_methods = Counter()
    order_currencies = Counter()
    with (DATA_DIR / "orders.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["amount_minor"] = int(row["amount_minor"])
            row["created_dt"] = parse_utc(row["created_at_utc"])
            orders[row["order_id"]] = row
            order_statuses[row["status"]] += 1
            order_methods[row["payment_method"]] += 1
            order_currencies[row["currency"]] += 1

    print("Orders total:", len(orders))
    print("Order statuses:", dict(order_statuses))
    print("Order methods:", dict(order_methods))
    print("Order currencies:", dict(order_currencies))

    # 3. Load provider_charges
    charges_by_order = defaultdict(list)
    charge_statuses = Counter()
    charge_currencies = Counter()
    with (DATA_DIR / "provider_charges.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["amount_minor"] = int(row["amount_minor"])
            row["created_dt"] = parse_utc(row["created_at_utc"])
            charges_by_order[row["order_id"]].append(row)
            charge_statuses[row["status"]] += 1
            charge_currencies[row["currency"]] += 1

    print("Charges total:", sum(len(v) for v in charges_by_order.values()))
    print("Charge statuses:", dict(charge_statuses))
    print("Charge currencies:", dict(charge_currencies))

    # Check if any charge references unknown order_id or mismatched currency
    unknown_orders = [oid for oid in charges_by_order if oid not in orders]
    print("Unknown orders in charges:", len(unknown_orders))
    mismatched_ccy = [
        (oid, orders[oid]["currency"], c["currency"])
        for oid, clist in charges_by_order.items()
        for c in clist
        if orders[oid]["currency"] != c["currency"]
    ]
    print("Mismatched currencies:", len(mismatched_ccy))

    # 4. Identify extra charges and outstanding refunds
    extra_charges = []
    orders_needing_refund = 0
    outstanding_by_ccy = Counter()
    outstanding_by_user_cny = Counter()  # exact scaled by 100 or float? Wait: 1 USD = 7.10 CNY = 710/100
    # Wait: 1 USD = 100 cents, 1 CNY = 100 fen.
    # So 1 USD cent = 7.10 CNY fen!
    user_ccy_breakdown = defaultdict(Counter)

    for oid, o in orders.items():
        owed = o["amount_minor"] if o["status"] == "paid" else 0
        clist = sorted(charges_by_order.get(oid, []), key=lambda c: (c["created_dt"], c["charge_id"]))

        # Extra charge: charge (succeeded or refunded) pushing running total of successful charges
        # (taken in created_at_utc order) above owed amount.
        running_successful = 0
        for c in clist:
            if c["status"] in ("succeeded", "refunded"):
                running_successful += c["amount_minor"]
                if running_successful > owed:
                    extra_charges.append((c["created_dt"], c["created_at_utc"], oid, c["charge_id"], c["status"], o["status"], c["amount_minor"], owed, running_successful))

        # Outstanding refund = (sum of charges whose status is 'succeeded') - owed, floored at 0
        succeeded_sum = sum(c["amount_minor"] for c in clist if c["status"] == "succeeded")
        outstanding = max(0, succeeded_sum - owed)
        if outstanding > 0:
            orders_needing_refund += 1
            ccy = o["currency"]
            outstanding_by_ccy[ccy] += outstanding
            user_ccy_breakdown[o["user_id"]][ccy] += outstanding

    extra_charges.sort(key=lambda x: (x[0], x[3]))
    print("\nTotal extra charges:", len(extra_charges))
    if extra_charges:
        print("First 5 extra charges:")
        for ec in extra_charges[:5]:
            print(" ", ec[1:])
        print("Last 5 extra charges:")
        for ec in extra_charges[-5:]:
            print(" ", ec[1:])

    # Print deploys around extra charges
    print("\nDeploys:")
    for did, d in deploys.items():
        print(f"  {did}: {d['service']} {d['version']} [{d['started_at_utc']} .. {d['finished_at_utc']}] {d['summary']}")

    # Check if any extra charge occurred before DEP-7731 finished or after DEP-7740 finished
    culprit = deploys["DEP-7731"]
    mitigation = deploys["DEP-7740"]
    t_culprit_start = parse_utc(culprit["started_at_utc"])
    t_culprit_fin = parse_utc(culprit["finished_at_utc"])
    t_mit_start = parse_utc(mitigation["started_at_utc"])
    t_mit_fin = parse_utc(mitigation["finished_at_utc"])

    before_culprit = [ec for ec in extra_charges if ec[0] < t_culprit_fin]
    before_culprit_start = [ec for ec in extra_charges if ec[0] < t_culprit_start]
    after_mit_fin = [ec for ec in extra_charges if ec[0] >= t_mit_fin]
    print(f"\nExtra charges before DEP-7731 started: {len(before_culprit_start)}")
    print(f"Extra charges before DEP-7731 finished: {len(before_culprit)}")
    if before_culprit:
        for ec in before_culprit:
            print("  early extra:", ec[1:])
    print(f"Extra charges at/after DEP-7740 finished: {len(after_mit_fin)}")
    if after_mit_fin:
        for ec in after_mit_fin[:10]:
            print("  late extra:", ec[1:])

    # First extra charge after culprit finished_at_utc (inclusive)
    after_culprit = [ec for ec in extra_charges if ec[0] >= t_culprit_fin]
    print("\nFirst extra charge >= culprit finished_at_utc:", after_culprit[0][1:] if after_culprit else None)

    print("\nQ4 orders_needing_refund:", orders_needing_refund)
    print("Q5 outstanding_refund_minor:", dict(outstanding_by_ccy))

    # Q6 top_user
    user_totals = []
    for uid, ccy_map in user_ccy_breakdown.items():
        cny = ccy_map.get("CNY", 0)
        usd = ccy_map.get("USD", 0)
        # 1 USD = 7.10 CNY => 1 USD cent = 7.10 CNY fen
        # Use integer tenths to avoid float precision issues: total_tenths = cny * 10 + usd * 71
        total_cny_float = cny + usd * 7.10
        total_cny_rounded = (cny * 10 + usd * 71 + 5) // 10  # wait, let's check both round() and half-up!
        user_totals.append((total_cny_float, round(total_cny_float), total_cny_rounded, uid, dict(ccy_map)))
    user_totals.sort(reverse=True)
    print("\nTop 10 users by outstanding CNY minor:")
    for item in user_totals[:10]:
        print(" ", item)

    # Q7 gateway 502 in [t_culprit_fin, t_mit_fin)
    gw_re = re.compile(
        r'^(\S+) - (\S+) \[([^\]]+)\] "(\S+) (\S+) [^"]+" (\d+) rt=([\d.]+) upstream=(\S+) trace=(\S+)$'
    )
    gw_502_checkout = 0
    gw_502_all = 0
    gw_other_checkout = Counter()
    with (DATA_DIR / "logs/gateway-access.log").open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            m = gw_re.match(line.rstrip("\n"))
            if not m:
                raise ValueError(f"Unparsed gateway line {line_no}: {line!r}")
            ts_str, method, path, status = m.group(3), m.group(4), m.group(5), int(m.group(6))
            dt_utc = parse_gw_cst(ts_str)
            if t_culprit_fin <= dt_utc < t_mit_fin:
                if status == 502:
                    gw_502_all += 1
                if method == "POST" and path == "/api/v2/checkout":
                    gw_other_checkout[status] += 1
                    if status == 502:
                        gw_502_checkout += 1
    print(f"\nQ7 gateway_checkout_502_in_window: {gw_502_checkout} (all 502 in window: {gw_502_all}, checkout statuses in window: {dict(gw_other_checkout)})")

    # Q8 payment-svc charge.result stats
    before_start = t_culprit_fin - timedelta(hours=2)
    before_durations = []
    during_durations = []
    during_results = Counter()

    kv_re = re.compile(r'(\w+)=([^\s]+)')
    with (DATA_DIR / "logs/payment-svc.log").open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            parts = line.strip().split(" ", 1)
            dt_utc = parse_utc(parts[0])
            kvs = dict(kv_re.findall(line))
            if kvs.get("event") != "charge.result":
                continue
            dur = int(kvs["duration_ms"])
            res = kvs["result"]
            if before_start <= dt_utc < t_culprit_fin:
                before_durations.append(dur)
            elif t_culprit_fin <= dt_utc < t_mit_fin:
                during_durations.append(dur)
                during_results[res] += 1

    def p95_nearest_rank(vals: list[int]) -> int:
        s = sorted(vals)
        idx = math.ceil(0.95 * len(s)) - 1  # 1-based ceil(0.95 * n) -> 0-based -1
        return s[idx]

    before_p95 = p95_nearest_rank(before_durations)
    during_p95 = p95_nearest_rank(during_durations)
    timeout_cnt = during_results["timeout"]
    during_n = len(during_durations)
    timeout_pct = round(100.0 * timeout_cnt / during_n, 1)
    print(f"\nQ8 before: n={len(before_durations)}, p95={before_p95}")
    print(f"Q8 during: n={during_n}, p95={during_p95}, results={dict(during_results)}, timeout_rate={100.0 * timeout_cnt / during_n:.4f}% -> {timeout_pct}%")


if __name__ == "__main__":
    main()
