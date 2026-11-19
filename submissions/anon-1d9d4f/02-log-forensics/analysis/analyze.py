"""Forensic analysis script for ShopFast 2026-03-14 payment incident."""
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
OUT_JSON = Path(__file__).resolve().parents[1] / "answers.json"

CST = timezone(timedelta(hours=8))
UTC = timezone.utc


def parse_utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fmt_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def nearest_rank_p95(values: list[int]) -> int:
    if not values:
        raise ValueError("empty list")
    s = sorted(values)
    idx = math.ceil(0.95 * len(s)) - 1  # 1-based ceil(0.95*n) -> 0-based
    return s[idx]


def main() -> None:
    # 1. Load deploys
    deploys = {}
    with (DATA_DIR / "deploys.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            deploys[row["deploy_id"]] = row

    # 2. Load orders
    orders = {}
    with (DATA_DIR / "orders.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["amount_minor"] = int(row["amount_minor"])
            orders[row["order_id"]] = row

    print(f"Total orders: {len(orders)}")
    print("Order statuses:", Counter(o["status"] for o in orders.values()))
    print("Order currencies:", Counter(o["currency"] for o in orders.values()))
    print("Order payment_methods:", Counter(o["payment_method"] for o in orders.values()))

    # 3. Load provider_charges
    charges_by_order: dict[str, list[dict]] = defaultdict(list)
    total_charges = 0
    charge_statuses = Counter()
    with (DATA_DIR / "provider_charges.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            total_charges += 1
            row["amount_minor"] = int(row["amount_minor"])
            charge_statuses[row["status"]] += 1
            charges_by_order[row["order_id"]].append(row)

    print(f"Total charges: {total_charges}, statuses: {charge_statuses}")

    # Check if any charge references an unknown order or mismatched currency
    unknown_orders = [oid for oid in charges_by_order if oid not in orders]
    print(f"Charges with unknown order_id: {len(unknown_orders)}")
    currency_mismatches = 0
    for oid, clist in charges_by_order.items():
        oc = orders[oid]["currency"]
        for c in clist:
            if c["currency"] != oc:
                currency_mismatches += 1
    print(f"Currency mismatches between order and charge: {currency_mismatches}")

    # 4. Compute extra charges and outstanding refunds per finance-reconciliation.md
    extra_charges = []
    orders_needing_refund = 0
    outstanding_by_currency: dict[str, int] = defaultdict(int)
    outstanding_by_user_currency: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    refund_orders_detail = []

    for oid, o in orders.items():
        owed = o["amount_minor"] if o["status"] == "paid" else 0
        clist = charges_by_order.get(oid, [])

        # Outstanding refund = max(0, sum(succeeded charges) - owed)
        succeeded_sum = sum(c["amount_minor"] for c in clist if c["status"] == "succeeded")
        outstanding = max(0, succeeded_sum - owed)
        if outstanding > 0:
            orders_needing_refund += 1
            cur = o["currency"]
            outstanding_by_currency[cur] += outstanding
            outstanding_by_user_currency[o["user_id"]][cur] += outstanding
            refund_orders_detail.append((oid, o["user_id"], o["status"], cur, owed, succeeded_sum, outstanding))

        # Extra charges: status in ('succeeded', 'refunded'), sorted by created_at_utc
        # pushes running total above owed
        succ_or_ref = [c for c in clist if c["status"] in ("succeeded", "refunded")]
        succ_or_ref.sort(key=lambda c: (c["created_at_utc"], c["charge_id"]))
        running = 0
        for c in succ_or_ref:
            running += c["amount_minor"]
            if running > owed:
                extra_charges.append((c["created_at_utc"], oid, c))

    extra_charges.sort(key=lambda x: x[0])
    print(f"\nTotal extra charges (all time): {len(extra_charges)}")
    if extra_charges:
        print(f"Earliest extra charge (all time): {extra_charges[0][0]} order={extra_charges[0][1]} charge={extra_charges[0][2]['charge_id']}")
        print(f"Latest extra charge (all time):   {extra_charges[-1][0]} order={extra_charges[-1][1]} charge={extra_charges[-1][2]['charge_id']}")
        # Bucket extra charges by 10-min UTC window
        buckets = Counter(ts[:15] + "0Z" for ts, _, _ in extra_charges)
        print("Extra charges by 10-min UTC bucket:")
        for b in sorted(buckets):
            print(f"  {b}: {buckets[b]}")

    culprit_id = "DEP-7731"
    mitigation_id = "DEP-7740"
    culprit_fin = parse_utc(deploys[culprit_id]["finished_at_utc"])
    mitigation_fin = parse_utc(deploys[mitigation_id]["finished_at_utc"])
    print(f"\nCulprit {culprit_id} finished:    {fmt_utc(culprit_fin)}")
    print(f"Mitigation {mitigation_id} finished: {fmt_utc(mitigation_fin)}")

    extra_after_culprit = [x for x in extra_charges if parse_utc(x[0]) >= culprit_fin]
    first_extra_charge_utc = extra_after_culprit[0][0]
    print(f"First extra charge >= culprit finished: {first_extra_charge_utc} (order={extra_after_culprit[0][1]}, charge={extra_after_culprit[0][2]})")

    # Also check if any extra charges happened BEFORE culprit_fin or AFTER mitigation_fin
    extra_before = [x for x in extra_charges if parse_utc(x[0]) < culprit_fin]
    extra_after_mit = [x for x in extra_charges if parse_utc(x[0]) >= mitigation_fin]
    print(f"Extra charges before culprit_fin: {len(extra_before)}")
    for x in extra_before[:5]:
        print("  before:", x[0], x[1], x[2]["charge_id"], x[2]["status"], orders[x[1]]["status"])
    print(f"Extra charges >= mitigation_fin: {len(extra_after_mit)}")
    for x in extra_after_mit[:5]:
        print("  after_mit:", x[0], x[1], x[2]["charge_id"], x[2]["status"], orders[x[1]]["status"])

    # 5. Outstanding refunds and top user
    print(f"\norders_needing_refund: {orders_needing_refund}")
    print(f"outstanding_refund_minor: {dict(outstanding_by_currency)}")

    user_totals = []
    for uid, cur_map in outstanding_by_user_currency.items():
        cny = Decimal(cur_map.get("CNY", 0))
        usd = Decimal(cur_map.get("USD", 0))
        total_cny_exact = cny + usd * Decimal("7.10")
        total_cny_round = int(total_cny_exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        user_totals.append((total_cny_exact, total_cny_round, uid, dict(cur_map)))

    user_totals.sort(reverse=True)
    print("\nTop 5 users by outstanding refund (CNY minor):")
    for exact, rounded, uid, cmap in user_totals[:5]:
        print(f"  {uid}: exact={exact}, rounded={rounded}, breakdown={cmap}")

    top_user_id = user_totals[0][2]
    top_user_cny = user_totals[0][1]

    # 6. Gateway 502 count in [culprit_fin, mitigation_fin)
    # Format: <ip> - <user_id> [14/Mar/2026:06:00:00] "POST /api/v2/checkout HTTP/1.1" 502 rt=...
    gw_re = re.compile(
        r'^(\S+) - (\S+) \[(\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2})\] '
        r'"(\S+) (\S+) [^"]+" (\d{3}) rt=([0-9.]+) upstream=(\S+) trace=(\S+)'
    )
    gw_502_count = 0
    gw_502_samples = []
    gw_total = 0
    gw_bad = 0
    gw_502_by_10m = Counter()
    with (DATA_DIR / "logs" / "gateway-access.log").open(encoding="utf-8") as f:
        for line in f:
            gw_total += 1
            m = gw_re.match(line)
            if not m:
                gw_bad += 1
                continue
            ts_str, method, path, status = m.group(3), m.group(4), m.group(5), int(m.group(6))
            if method == "POST" and path == "/api/v2/checkout" and status == 502:
                dt_cst = datetime.strptime(ts_str, "%d/%b/%Y:%H:%M:%S").replace(tzinfo=CST)
                dt_utc = dt_cst.astimezone(UTC)
                gw_502_by_10m[dt_utc.strftime("%Y-%m-%dT%H:%M")[:15] + "0Z"] += 1
                if culprit_fin <= dt_utc < mitigation_fin:
                    gw_502_count += 1
                    if len(gw_502_samples) < 5:
                        gw_502_samples.append((fmt_utc(dt_utc), line.strip()))

    print(f"\nGateway lines parsed: {gw_total}, unparsed: {gw_bad}")
    print(f"gateway_checkout_502_in_window: {gw_502_count}")
    print("Gateway checkout 502 by 10-min UTC bucket:")
    for b in sorted(gw_502_by_10m):
        print(f"  {b}: {gw_502_by_10m[b]}")

    # 7. payment-svc charge.result stats
    before_start = culprit_fin - timedelta(hours=2)
    before_durs: list[int] = []
    during_durs: list[int] = []
    during_timeouts = 0
    during_results = Counter()
    before_results = Counter()

    # Also inspect sample traces for root cause verification
    version_seen = defaultdict(Counter)
    sample_multi_attempt_orders = []
    attempts_by_order = defaultdict(list)

    with (DATA_DIR / "logs" / "payment-svc.log").open(encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            ts = parse_utc(parts[0])
            # [payment-svc v2.14.0]
            ver = parts[3].rstrip("]")
            kv = {}
            for tok in parts[4:]:
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    kv[k] = v
            ev = kv.get("event")
            if ev == "charge.result":
                dur = int(kv["duration_ms"])
                res = kv["result"]
                if before_start <= ts < culprit_fin:
                    before_durs.append(dur)
                    before_results[res] += 1
                elif culprit_fin <= ts < mitigation_fin:
                    during_durs.append(dur)
                    during_results[res] += 1
                    if res == "timeout":
                        during_timeouts += 1
            if culprit_fin <= ts < mitigation_fin:
                version_seen["during"][ver] += 1
            elif before_start <= ts < culprit_fin:
                version_seen["before"][ver] += 1
            if kv.get("order") == extra_after_culprit[0][1]:
                attempts_by_order[kv["order"]].append(line.strip())

    before_p95 = nearest_rank_p95(before_durs)
    during_p95 = nearest_rank_p95(during_durs)
    during_timeout_pct = round(100.0 * during_timeouts / len(during_durs), 1)

    print(f"\npayment-svc before window [{fmt_utc(before_start)}, {fmt_utc(culprit_fin)}): n={len(before_durs)}, p95={before_p95}, results={before_results}")
    print(f"payment-svc during window [{fmt_utc(culprit_fin)}, {fmt_utc(mitigation_fin)}): n={len(during_durs)}, p95={during_p95}, timeouts={during_timeouts} ({during_timeout_pct}%), results={during_results}")
    print("Versions seen:", {k: dict(v) for k, v in version_seen.items()})

    print(f"\nSample payment-svc logs for first extra-charge order {extra_after_culprit[0][1]}:")
    for ln in attempts_by_order[extra_after_culprit[0][1]]:
        print(" ", ln)

    answers = {
        "culprit_deploy_id": culprit_id,
        "mitigation_deploy_id": mitigation_id,
        "first_extra_charge_utc": first_extra_charge_utc,
        "orders_needing_refund": orders_needing_refund,
        "outstanding_refund_minor": {
            "CNY": outstanding_by_currency["CNY"],
            "USD": outstanding_by_currency["USD"],
        },
        "top_user": {
            "user_id": top_user_id,
            "outstanding_cny_minor": top_user_cny,
        },
        "gateway_checkout_502_in_window": gw_502_count,
        "charge_result_stats": {
            "before_p95_ms": before_p95,
            "during_p95_ms": during_p95,
            "during_timeout_rate_pct": during_timeout_pct,
        },
    }

    OUT_JSON.write_text(json.dumps(answers, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {OUT_JSON}:")
    print(json.dumps(answers, indent=2))


if __name__ == "__main__":
    main()
