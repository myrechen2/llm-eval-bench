"""Log forensics analysis script for Task 02."""
from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[4] / "tasks" / "02-log-forensics" / "data"
CST = timezone(timedelta(hours=8))
UTC = timezone.utc


def parse_utc(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(UTC)


def parse_gateway_ts(s: str) -> datetime:
    # Format: 14/Mar/2026:06:00:00 in Asia/Shanghai (UTC+8)
    dt = datetime.strptime(s, "%d/%b/%Y:%H:%M:%S").replace(tzinfo=CST)
    return dt.astimezone(UTC)


def nearest_rank_p95(values: list[int]) -> int:
    assert values, "empty values"
    s = sorted(values)
    idx = math.ceil(0.95 * len(s)) - 1  # 1-based ceil(0.95*n) -> 0-based
    return s[idx]


def main() -> None:
    # 1. Load deploys
    deploys = {}
    with (DATA_DIR / "deploys.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["started_dt"] = parse_utc(row["started_at_utc"])
            row["finished_dt"] = parse_utc(row["finished_at_utc"])
            deploys[row["deploy_id"]] = row

    # 2. Load orders
    orders = {}
    order_statuses = Counter()
    order_currencies = Counter()
    order_methods = Counter()
    with (DATA_DIR / "orders.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            oid = row["order_id"]
            assert oid not in orders, f"duplicate order {oid}"
            amt = int(row["amount_minor"])
            row["amount_minor"] = amt
            orders[oid] = row
            order_statuses[row["status"]] += 1
            order_currencies[row["currency"]] += 1
            order_methods[row["payment_method"]] += 1

    print("Orders total:", len(orders))
    print("Order statuses:", dict(order_statuses))
    print("Order currencies:", dict(order_currencies))
    print("Order payment_methods:", dict(order_methods))

    # 3. Load provider_charges
    charges_by_order: dict[str, list[dict]] = defaultdict(list)
    charge_statuses = Counter()
    charge_currencies = Counter()
    seen_charge_ids = set()
    missing_orders = 0
    currency_mismatches = 0
    total_charges = 0

    with (DATA_DIR / "provider_charges.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            total_charges += 1
            cid = row["charge_id"]
            assert cid not in seen_charge_ids, f"duplicate charge {cid}"
            seen_charge_ids.add(cid)
            row["amount_minor"] = int(row["amount_minor"])
            row["created_dt"] = parse_utc(row["created_at_utc"])
            charge_statuses[row["status"]] += 1
            charge_currencies[row["currency"]] += 1
            oid = row["order_id"]
            if oid not in orders:
                missing_orders += 1
            else:
                if orders[oid]["currency"] != row["currency"]:
                    currency_mismatches += 1
            charges_by_order[oid].append(row)

    print("Charges total:", total_charges, "missing_orders:", missing_orders, "currency_mismatches:", currency_mismatches)
    print("Charge statuses:", dict(charge_statuses))
    print("Charge currencies:", dict(charge_currencies))

    # 4. Identify extra charges and outstanding refunds per finance-reconciliation.md
    # owed = amount_minor if order.status == 'paid' else 0
    # outstanding_refund = max(0, sum(c.amount_minor for c in charges if c.status == 'succeeded') - owed)
    # extra_charge = charge (status in ('succeeded', 'refunded')) that pushes running total
    #   (in created_at_utc order) above owed.
    extra_charges = []
    orders_needing_refund = 0
    outstanding_by_currency: Counter[str] = Counter()
    user_outstanding_by_currency: dict[str, Counter[str]] = defaultdict(Counter)
    order_refund_details = []
    tie_cases = 0

    for oid, order in orders.items():
        owed = order["amount_minor"] if order["status"] == "paid" else 0
        olist = charges_by_order.get(oid, [])

        # Outstanding refund
        succeeded_sum = sum(c["amount_minor"] for c in olist if c["status"] == "succeeded")
        outstanding = max(0, succeeded_sum - owed)
        if outstanding > 0:
            orders_needing_refund += 1
            cur = order["currency"]
            outstanding_by_currency[cur] += outstanding
            user_outstanding_by_currency[order["user_id"]][cur] += outstanding
            order_refund_details.append((oid, order["user_id"], order["status"], order["payment_method"], cur, order["amount_minor"], succeeded_sum, outstanding, len(olist)))

        # Extra charges (status succeeded or refunded, in created_at_utc order)
        succ_or_ref = [c for c in olist if c["status"] in ("succeeded", "refunded")]
        # Check for ties in created_at_utc
        ts_list = [c["created_dt"] for c in succ_or_ref]
        if len(ts_list) != len(set(ts_list)) and sum(c["amount_minor"] for c in succ_or_ref) > owed:
            tie_cases += 1
        succ_or_ref.sort(key=lambda c: (c["created_dt"], c["charge_id"]))
        running = 0
        for c in succ_or_ref:
            running += c["amount_minor"]
            if running > owed:
                extra_charges.append((c, order))

    print("\nExtra charges total:", len(extra_charges), "tie_cases:", tie_cases)
    extra_charges.sort(key=lambda x: x[0]["created_dt"])
    if extra_charges:
        print("Earliest 10 extra charges:")
        for c, o in extra_charges[:10]:
            print(f"  {c['created_at_utc']} {c['charge_id']} order={o['order_id']} o_status={o['status']} c_status={c['status']} amt={c['amount_minor']} {c['currency']} idem={c['idempotency_key']}")
        print("Latest 10 extra charges:")
        for c, o in extra_charges[-10:]:
            print(f"  {c['created_at_utc']} {c['charge_id']} order={o['order_id']} o_status={o['status']} c_status={c['status']} amt={c['amount_minor']} {c['currency']} idem={c['idempotency_key']}")

    # Bucket extra charges by 10-minute UTC intervals to see exact incident window
    buckets = Counter()
    for c, _ in extra_charges:
        dt = c["created_dt"]
        b = dt.replace(minute=(dt.minute // 10) * 10, second=0, microsecond=0).strftime("%H:%M")
        buckets[b] += 1
    print("\nExtra charges by 10-min UTC bucket:")
    for k in sorted(buckets):
        print(f"  {k}Z: {buckets[k]}")

    # Check culprit and mitigation deploys
    culprit_id = "DEP-7731"
    mitigation_id = "DEP-7740"
    culprit_end = deploys[culprit_id]["finished_dt"]
    mitigation_end = deploys[mitigation_id]["finished_dt"]
    print(f"\nCulprit {culprit_id} finished: {deploys[culprit_id]['finished_at_utc']}")
    print(f"Mitigation {mitigation_id} finished: {deploys[mitigation_id]['finished_at_utc']}")

    # Extra charges before culprit_end, during [culprit_end, mitigation_end), after mitigation_end
    before_ec = [x for x in extra_charges if x[0]["created_dt"] < culprit_end]
    during_ec = [x for x in extra_charges if culprit_end <= x[0]["created_dt"] < mitigation_end]
    after_ec = [x for x in extra_charges if x[0]["created_dt"] >= mitigation_end]
    print(f"Extra charges: before={len(before_ec)}, during={len(during_ec)}, after={len(after_ec)}")
    if before_ec:
        print("  Before culprit extra charges:")
        for c, o in before_ec:
            print(f"    {c['created_at_utc']} {c['charge_id']} order={o['order_id']} o_status={o['status']} c_status={c['status']} amt={c['amount_minor']}")
    if after_ec:
        print("  After mitigation extra charges:")
        for c, o in after_ec[:10]:
            print(f"    {c['created_at_utc']} {c['charge_id']} order={o['order_id']} o_status={o['status']} c_status={c['status']} amt={c['amount_minor']}")

    first_extra_after_culprit = next(c["created_at_utc"] for c, _ in extra_charges if c["created_dt"] >= culprit_end)
    print("first_extra_charge_utc:", first_extra_after_culprit)

    # Breakdown of orders needing refund by order status & payment method
    print("\norders_needing_refund:", orders_needing_refund)
    print("outstanding_refund_minor:", dict(outstanding_by_currency))
    status_breakdown = Counter((x[2], x[3]) for x in order_refund_details)
    print("Refund orders by (order_status, payment_method):", dict(status_breakdown))

    # Top users by CNY-equivalent outstanding refund (1 USD = 7.10 CNY)
    user_totals = []
    for uid, cur_map in user_outstanding_by_currency.items():
        cny = cur_map.get("CNY", 0)
        usd = cur_map.get("USD", 0)
        exact_dec = Decimal(cny) + Decimal(usd) * Decimal("7.10")
        rounded_half_up = int(exact_dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        rounded_py = round(cny + usd * 7.10)
        user_totals.append((exact_dec, rounded_half_up, rounded_py, uid, cny, usd))
    user_totals.sort(reverse=True)
    print("\nTop 10 users by outstanding refund (CNY minor):")
    for exact_dec, r_hu, r_py, uid, cny, usd in user_totals[:10]:
        print(f"  {uid}: exact={exact_dec} half_up={r_hu} py_round={r_py} (CNY={cny}, USD={usd})")

    # 5. Gateway log analysis
    gw_re = re.compile(
        r'^(\S+) - (\S+) \[([^\]]+)\] "(\S+) (\S+) HTTP/[^"]+" (\d+) rt=([\d.]+) upstream=(\S+) trace=(\S+)$'
    )
    gw_total = 0
    gw_unmatched = 0
    gw_checkout_502_in_window = 0
    gw_502_by_path_in_window = Counter()
    gw_checkout_status_in_window = Counter()
    gw_checkout_502_before = 0
    gw_checkout_502_after = 0
    gw_boundary_hits = []
    gw_502_samples = []

    with (DATA_DIR / "logs" / "gateway-access.log").open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            gw_total += 1
            m = gw_re.match(line.rstrip("\n"))
            if not m:
                gw_unmatched += 1
                continue
            ip, uid, ts_str, method, path, status_s, rt_s, upstream, trace = m.groups()
            status = int(status_s)
            dt = parse_gateway_ts(ts_str)
            if dt == culprit_end or dt == mitigation_end:
                if method == "POST" and path == "/api/v2/checkout" and status == 502:
                    gw_boundary_hits.append((dt.isoformat(), line.strip()))
            if culprit_end <= dt < mitigation_end:
                if status == 502:
                    gw_502_by_path_in_window[(method, path)] += 1
                if method == "POST" and path == "/api/v2/checkout":
                    gw_checkout_status_in_window[status] += 1
                    if status == 502:
                        gw_checkout_502_in_window += 1
                        if len(gw_502_samples) < 5:
                            gw_502_samples.append((line_no, dt.isoformat(), line.strip()))
            elif dt < culprit_end and method == "POST" and path == "/api/v2/checkout" and status == 502:
                gw_checkout_502_before += 1
            elif dt >= mitigation_end and method == "POST" and path == "/api/v2/checkout" and status == 502:
                gw_checkout_502_after += 1

    print(f"\nGateway lines: {gw_total}, unmatched: {gw_unmatched}")
    print(f"POST /api/v2/checkout 502: before={gw_checkout_502_before}, in_window={gw_checkout_502_in_window}, after={gw_checkout_502_after}")
    print("Gateway 502 by (method, path) in window:", dict(gw_502_by_path_in_window))
    print("Gateway POST /api/v2/checkout status in window:", dict(gw_checkout_status_in_window))
    print("Boundary hits:", gw_boundary_hits)

    # 6. payment-svc log analysis
    before_start = culprit_end - timedelta(hours=2)
    pay_line_re = re.compile(r"^(\S+)\s+(\S+)\s+\[payment-svc\s+(\S+)\]\s+(.*)$")
    before_durations = []
    during_durations = []
    during_results = Counter()
    before_results = Counter()
    pay_events = Counter()
    pay_versions_by_event = Counter()
    pay_unmatched = 0
    pay_total = 0

    # Also track per-version timeout/retry behavior
    version_attempts = defaultdict(Counter)
    sample_logs_by_ver = defaultdict(list)

    with (DATA_DIR / "logs" / "payment-svc.log").open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            pay_total += 1
            m = pay_line_re.match(line.rstrip("\n"))
            if not m:
                pay_unmatched += 1
                continue
            ts_s, level, ver, rest = m.groups()
            dt = parse_utc(ts_s)
            kv = {}
            for tok in rest.split():
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    kv[k] = v
            ev = kv.get("event", "")
            pay_events[ev] += 1
            pay_versions_by_event[(ver, ev)] += 1
            if "attempt" in kv:
                version_attempts[ver][kv["attempt"]] += 1

            if ev == "charge.result":
                dur = int(kv["duration_ms"])
                res = kv["result"]
                if before_start <= dt < culprit_end:
                    before_durations.append(dur)
                    before_results[res] += 1
                elif culprit_end <= dt < mitigation_end:
                    during_durations.append(dur)
                    during_results[res] += 1

            if len(sample_logs_by_ver[(ver, ev)]) < 3:
                sample_logs_by_ver[(ver, ev)].append((line_no, line.strip()))

    print(f"\npayment-svc lines: {pay_total}, unmatched: {pay_unmatched}")
    print("Events:", dict(pay_events))
    print("By (ver, event):", {f"{k[0]}:{k[1]}": v for k, v in sorted(pay_versions_by_event.items())})
    print("Attempts by ver:", {k: dict(v) for k, v in version_attempts.items()})
    print(f"Before window [{before_start.isoformat()}, {culprit_end.isoformat()}): n={len(before_durations)}, results={dict(before_results)}")
    print(f"During window [{culprit_end.isoformat()}, {mitigation_end.isoformat()}): n={len(during_durations)}, results={dict(during_results)}")

    before_p95 = nearest_rank_p95(before_durations)
    during_p95 = nearest_rank_p95(during_durations)
    timeout_pct = during_results["timeout"] / len(during_durations) * 100.0
    print(f"before_p95_ms={before_p95}, during_p95_ms={during_p95}, during_timeout_rate_pct={timeout_pct:.4f}% (rounded: {round(timeout_pct, 1)})")

    print("\nSample payment-svc logs by (ver, event):")
    for k in sorted(sample_logs_by_ver):
        print(f"  --- {k} ---")
        for ln, txt in sample_logs_by_ver[k][:2]:
            print(f"    L{ln}: {txt}")


if __name__ == "__main__":
    main()
