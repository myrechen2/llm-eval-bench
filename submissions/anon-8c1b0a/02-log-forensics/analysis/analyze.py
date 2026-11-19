import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[4] / "tasks" / "02-log-forensics" / "data"


def parse_utc_iso(ts_str: str) -> datetime:
    # Handle both '2026-03-14T06:40:00Z' and '2026-03-14T06:40:00.123Z'
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    return datetime.fromisoformat(ts_str)


def nearest_rank_p95(values: list[int]) -> int:
    s = sorted(values)
    n = len(s)
    idx = math.ceil(0.95 * n) - 1  # 1-based to 0-based
    return s[idx]


def main():
    # 1. Load deploys
    deploys = {}
    with open(DATA_DIR / "deploys.csv", "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            deploys[row["deploy_id"]] = row

    culprit_deploy_id = "DEP-7731"
    mitigation_deploy_id = "DEP-7740"
    culprit_finished_str = deploys[culprit_deploy_id]["finished_at_utc"]
    mitigation_finished_str = deploys[mitigation_deploy_id]["finished_at_utc"]
    culprit_finished_dt = parse_utc_iso(culprit_finished_str)
    mitigation_finished_dt = parse_utc_iso(mitigation_finished_str)
    before_start_dt = culprit_finished_dt - timedelta(hours=2)

    print(f"before window: [{before_start_dt.isoformat()}, {culprit_finished_dt.isoformat()})")
    print(f"during window: [{culprit_finished_dt.isoformat()}, {mitigation_finished_dt.isoformat()})")

    # 2. Load orders & provider_charges
    orders = {}
    with open(DATA_DIR / "orders.csv", "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["amount_minor"] = int(row["amount_minor"])
            orders[row["order_id"]] = row

    charges_by_order = defaultdict(list)
    with open(DATA_DIR / "provider_charges.csv", "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["amount_minor"] = int(row["amount_minor"])
            charges_by_order[row["order_id"]].append(row)

    extra_charges = []
    orders_needing_refund = 0
    outstanding_refund_minor = {"CNY": 0, "USD": 0}
    user_outstanding = defaultdict(lambda: {"CNY": 0, "USD": 0})

    for oid, order in orders.items():
        owed = order["amount_minor"] if order["status"] == "paid" else 0
        ocharges = charges_by_order.get(oid, [])

        succeeded_sum = sum(c["amount_minor"] for c in ocharges if c["status"] == "succeeded")
        outstanding = max(0, succeeded_sum - owed)
        if outstanding > 0:
            orders_needing_refund += 1
            curr = order["currency"]
            outstanding_refund_minor[curr] += outstanding
            user_outstanding[order["user_id"]][curr] += outstanding

        succ_or_ref = [c for c in ocharges if c["status"] in ("succeeded", "refunded")]
        succ_or_ref.sort(key=lambda c: c["created_at_utc"])
        running = 0
        for c in succ_or_ref:
            running += c["amount_minor"]
            if running > owed:
                extra_charges.append((c["created_at_utc"], oid, c))

    extra_charges.sort(key=lambda x: x[0])
    extra_after_culprit = [ec for ec in extra_charges if ec[0] >= culprit_finished_str]
    first_extra_charge_utc = extra_after_culprit[0][0]

    user_totals = []
    for uid, amounts in user_outstanding.items():
        cny_minor_exact = Decimal(amounts["CNY"]) + Decimal(amounts["USD"]) * Decimal("7.10")
        cny_minor_rounded = int(cny_minor_exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        user_totals.append((cny_minor_rounded, uid, amounts))
    user_totals.sort(reverse=True)
    top_user_cny_minor, top_user_id, top_user_breakdown = user_totals[0]

    # 3. Parse gateway-access.log for Q7:
    # POST /api/v2/checkout with status 502 in [culprit_finished_utc, mitigation_finished_utc)
    # Note: gateway logs in Asia/Shanghai (UTC+8) without offset!
    shanghai_tz = timezone(timedelta(hours=8))
    gw_re = re.compile(
        r'^\S+ - (\S+) \[(\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2})\] "([A-Z]+) ([^ ]+) HTTP/1\.1" (\d{3}) rt=([0-9.]+) upstream=(\S+) trace=(\S+)$'
    )
    gateway_checkout_502_in_window = 0
    total_checkout_502 = 0
    with open(DATA_DIR / "logs" / "gateway-access.log", "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            m = gw_re.match(line)
            if not m:
                raise ValueError(f"Unmatched gateway line {line_no}: {line}")
            uid, ts_local_str, method, path, status_str, rt_str, upstream, trace = m.groups()
            if method == "POST" and path == "/api/v2/checkout" and status_str == "502":
                total_checkout_502 += 1
                dt_local = datetime.strptime(ts_local_str, "%d/%b/%Y:%H:%M:%S").replace(tzinfo=shanghai_tz)
                dt_utc = dt_local.astimezone(timezone.utc)
                if culprit_finished_dt <= dt_utc < mitigation_finished_dt:
                    gateway_checkout_502_in_window += 1

    print(f"Total POST /api/v2/checkout 502s: {total_checkout_502}, in window: {gateway_checkout_502_in_window}")

    # 4. Parse payment-svc.log for Q8:
    # event=charge.result lines:
    # before_p95_ms: [culprit finished - 2h, culprit finished)
    # during_p95_ms: [culprit finished, mitigation finished)
    # during_timeout_rate_pct: result=timeout share in during window, percentage rounded to 1 decimal place
    pay_re = re.compile(
        r"^(\S+) (\S+)\s+\[payment-svc ([^\]]+)\] (.+)$"
    )
    before_durations = []
    during_durations = []
    during_timeouts = 0
    events_seen = set()
    sample_v2134_timeout = []
    sample_v2140_retry = []
    sample_v2142_retry = []
    order_001701_logs = []
    order_003221_logs = []
    order_003222_logs = []

    with open(DATA_DIR / "logs" / "payment-svc.log", "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            m = pay_re.match(line)
            if not m:
                raise ValueError(f"Unmatched payment-svc line {line_no}: {line}")
            ts_str, level, ver, kv_str = m.groups()
            dt_utc = parse_utc_iso(ts_str)
            kvs = dict(item.split("=", 1) for item in kv_str.split())
            ev = kvs["event"]
            events_seen.add(ev)

            if kvs.get("order") == "O0314-001701":
                order_001701_logs.append(line)
            if kvs.get("order") == "O0314-003221":
                order_003221_logs.append(line)
            if kvs.get("order") == "O0314-003222":
                order_003222_logs.append(line)

            if ver == "v2.13.4" and ev != "charge.request" and kvs.get("result") != "succeeded" and len(sample_v2134_timeout) < 10:
                sample_v2134_timeout.append(line)
            if ver == "v2.14.0" and kvs.get("attempt") in ("2", "3") and len(sample_v2140_retry) < 10:
                sample_v2140_retry.append(line)
            if ver == "v2.14.2" and kvs.get("attempt") in ("2", "3") and len(sample_v2142_retry) < 10:
                sample_v2142_retry.append(line)

            if ev == "charge.result":
                dur = int(kvs["duration_ms"])
                res = kvs["result"]
                if before_start_dt <= dt_utc < culprit_finished_dt:
                    before_durations.append(dur)
                elif culprit_finished_dt <= dt_utc < mitigation_finished_dt:
                    during_durations.append(dur)
                    if res == "timeout":
                        during_timeouts += 1

    print(f"\npayment-svc events seen: {events_seen}")
    print(f"before_durations count: {len(before_durations)}, p95: {nearest_rank_p95(before_durations)}")
    print(f"during_durations count: {len(during_durations)}, p95: {nearest_rank_p95(during_durations)}")
    timeout_rate = (during_timeouts / len(during_durations)) * 100.0
    print(f"during_timeouts: {during_timeouts} / {len(during_durations)} = {timeout_rate:.6f}% -> rounded 1 dec: {round(timeout_rate, 1)}")

    print("\n--- Order O0314-001701 logs (pre-incident extra charge) ---")
    for l in order_001701_logs:
        print(" ", l)
    print("\n--- Order O0314-003221 logs (first incident extra charge) ---")
    for l in order_003221_logs:
        print(" ", l)
    print("\n--- Order O0314-003222 logs (payment_failed with hidden charges) ---")
    for l in order_003222_logs:
        print(" ", l)
    print("\n--- Sample v2.13.4 non-succeeded events ---")
    for l in sample_v2134_timeout:
        print(" ", l)
    print("\n--- Sample v2.14.2 retries ---")
    for l in sample_v2142_retry:
        print(" ", l)

    answers = {
        "culprit_deploy_id": culprit_deploy_id,
        "mitigation_deploy_id": mitigation_deploy_id,
        "first_extra_charge_utc": first_extra_charge_utc,
        "orders_needing_refund": orders_needing_refund,
        "outstanding_refund_minor": outstanding_refund_minor,
        "top_user": {
            "user_id": top_user_id,
            "outstanding_cny_minor": top_user_cny_minor,
        },
        "gateway_checkout_502_in_window": gateway_checkout_502_in_window,
        "charge_result_stats": {
            "before_p95_ms": nearest_rank_p95(before_durations),
            "during_p95_ms": nearest_rank_p95(during_durations),
            "during_timeout_rate_pct": round(timeout_rate, 1),
        },
    }
    print("\n=== Computed answers.json ===")
    print(json.dumps(answers, indent=2))


if __name__ == "__main__":
    main()
