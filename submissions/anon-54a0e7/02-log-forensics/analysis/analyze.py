import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[4]
DATA_DIR = BASE_DIR / "tasks/02-log-forensics/data"
OUT_DIR = Path(__file__).resolve().parent.parent


def load_orders():
    orders = {}
    with open(DATA_DIR / "orders.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["amount_minor"] = int(row["amount_minor"])
            orders[row["order_id"]] = row
    return orders


def load_charges():
    charges = []
    with open(DATA_DIR / "provider_charges.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["amount_minor"] = int(row["amount_minor"])
            charges.append(row)
    return charges


def nearest_rank_p95(vals: list[int]) -> int:
    s = sorted(vals)
    idx = math.ceil(0.95 * len(s)) - 1
    return s[idx]


def main():
    orders = load_orders()
    charges = load_charges()

    charges_by_order = defaultdict(list)
    for c in charges:
        charges_by_order[c["order_id"]].append(c)

    culprit_deploy_id = "DEP-7731"
    mitigation_deploy_id = "DEP-7740"
    culprit_fin_str = "2026-03-14T06:40:00Z"
    mitigation_fin_str = "2026-03-14T08:02:30Z"

    extra_charges = []
    orders_needing_refund = 0
    outstanding_by_curr = {"CNY": 0, "USD": 0}
    user_outstanding = defaultdict(lambda: {"CNY": 0, "USD": 0})

    for oid, o in orders.items():
        owed = o["amount_minor"] if o["status"] == "paid" else 0
        ocharges = charges_by_order.get(oid, [])

        succ_charges = [c for c in ocharges if c["status"] in ("succeeded", "refunded")]
        succ_charges.sort(key=lambda c: (c["created_at_utc"], c["charge_id"]))
        running = 0
        for c in succ_charges:
            running += c["amount_minor"]
            if running > owed:
                extra_charges.append(c)

        curr_succeeded_sum = sum(c["amount_minor"] for c in ocharges if c["status"] == "succeeded")
        outstanding = max(0, curr_succeeded_sum - owed)
        if outstanding > 0:
            orders_needing_refund += 1
            outstanding_by_curr[o["currency"]] += outstanding
            user_outstanding[o["user_id"]][o["currency"]] += outstanding

    extra_charges.sort(key=lambda c: c["created_at_utc"])
    first_extra_charge_utc = next(
        c["created_at_utc"] for c in extra_charges if c["created_at_utc"] >= culprit_fin_str
    )

    user_totals = []
    for uid, currs in user_outstanding.items():
        cny_minor = round(currs["CNY"] + currs["USD"] * 7.10)
        user_totals.append((cny_minor, uid))
    user_totals.sort(reverse=True)
    top_cny_minor, top_user_id = user_totals[0]

    t_start = datetime(2026, 3, 14, 6, 40, 0, tzinfo=timezone.utc)
    t_end = datetime(2026, 3, 14, 8, 2, 30, tzinfo=timezone.utc)
    t_before_start = t_start - timedelta(hours=2)
    tz_sh = timezone(timedelta(hours=8))

    gw_re = re.compile(
        r'^(\S+) - (\S+) \[(\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2})\] "([^"]+)" (\d{3}) rt=([0-9.]+) upstream=(\S+) trace=(\S+)$'
    )
    gateway_checkout_502_in_window = 0
    with open(DATA_DIR / "logs/gateway-access.log", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = gw_re.match(line)
            if not m:
                continue
            ts_str, req, status = m.group(3), m.group(4), int(m.group(5))
            dt_local = datetime.strptime(ts_str, "%d/%b/%Y:%H:%M:%S").replace(tzinfo=tz_sh)
            dt_utc = dt_local.astimezone(timezone.utc)
            if t_start <= dt_utc < t_end and req.startswith("POST /api/v2/checkout ") and status == 502:
                gateway_checkout_502_in_window += 1

    before_durations = []
    during_durations = []
    during_timeouts = 0
    pay_re = re.compile(r"^(\S+)\s+\S+\s+\[payment-svc\s+([^\]]+)\]\s+(.*)$")
    with open(DATA_DIR / "logs/payment-svc.log", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = pay_re.match(line)
            if not m:
                continue
            ts_str, _, kv_str = m.group(1), m.group(2), m.group(3)
            dt_utc = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            kvs = dict(item.split("=", 1) for item in kv_str.split())
            if kvs.get("event") == "charge.result":
                dur = int(kvs["duration_ms"])
                res = kvs["result"]
                if t_before_start <= dt_utc < t_start:
                    before_durations.append(dur)
                elif t_start <= dt_utc < t_end:
                    during_durations.append(dur)
                    if res == "timeout":
                        during_timeouts += 1

    answers = {
        "culprit_deploy_id": culprit_deploy_id,
        "mitigation_deploy_id": mitigation_deploy_id,
        "first_extra_charge_utc": first_extra_charge_utc,
        "orders_needing_refund": orders_needing_refund,
        "outstanding_refund_minor": outstanding_by_curr,
        "top_user": {
            "user_id": top_user_id,
            "outstanding_cny_minor": top_cny_minor,
        },
        "gateway_checkout_502_in_window": gateway_checkout_502_in_window,
        "charge_result_stats": {
            "before_p95_ms": nearest_rank_p95(before_durations),
            "during_p95_ms": nearest_rank_p95(during_durations),
            "during_timeout_rate_pct": round(during_timeouts * 100.0 / len(during_durations), 1),
        },
    }

    with open(OUT_DIR / "answers.json", "w", encoding="utf-8") as f:
        json.dump(answers, f, indent=2)
        f.write("\n")

    print(json.dumps(answers, indent=2))


if __name__ == "__main__":
    main()
