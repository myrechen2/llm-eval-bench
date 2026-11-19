import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[4] / "tasks" / "02-log-forensics" / "data"
OUT_DIR = Path(__file__).resolve().parents[1]

CST = timezone(timedelta(hours=8))


def parse_utc(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts).astimezone(timezone.utc)


def nearest_rank_p95(vals: list[int]) -> int:
    s = sorted(vals)
    idx = math.ceil(0.95 * len(s)) - 1
    return s[idx]


def main() -> None:
    # 1. Load deploys
    deploys = {}
    with open(DATA_DIR / "deploys.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            deploys[row["deploy_id"]] = row

    culprit_id = "DEP-7731"      # payment-svc v2.14.0
    mitigation_id = "DEP-7740"   # payment-svc v2.13.4 rollback
    t_start = parse_utc(deploys[culprit_id]["finished_at_utc"])
    t_end = parse_utc(deploys[mitigation_id]["finished_at_utc"])
    t_before_start = t_start - timedelta(hours=2)

    print(f"Culprit {culprit_id} finished:    {t_start.isoformat()}")
    print(f"Mitigation {mitigation_id} finished: {t_end.isoformat()}")

    # 2. Load orders
    orders = {}
    currencies = set()
    with open(DATA_DIR / "orders.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["amount_minor"] = int(row["amount_minor"])
            orders[row["order_id"]] = row
            currencies.add(row["currency"])
    print(f"Loaded {len(orders)} orders, currencies: {sorted(currencies)}")

    # 3. Load provider_charges
    charges_by_order = defaultdict(list)
    with open(DATA_DIR / "provider_charges.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["amount_minor"] = int(row["amount_minor"])
            row["created_dt"] = parse_utc(row["created_at_utc"])
            charges_by_order[row["order_id"]].append(row)

    # 4. Extra charges & outstanding refunds
    extra_charges_all = []
    extra_charges_after_culprit = []
    orders_needing_refund = 0
    outstanding_by_currency = defaultdict(int)
    user_outstanding = defaultdict(lambda: defaultdict(int))

    for oid, order in orders.items():
        owed = order["amount_minor"] if order["status"] == "paid" else 0
        ocharges = charges_by_order.get(oid, [])

        # Extra charges: status in ('succeeded', 'refunded') in created_at_utc order
        succ_or_ref = sorted(
            (c for c in ocharges if c["status"] in ("succeeded", "refunded")),
            key=lambda c: (c["created_dt"], c["charge_id"]),
        )
        running = 0
        for c in succ_or_ref:
            running += c["amount_minor"]
            if running > owed:
                extra_charges_all.append(c)
                if c["created_dt"] >= t_start:
                    extra_charges_after_culprit.append(c)

        # Outstanding refund: sum(succeeded) - owed, floored at 0
        succeeded_sum = sum(c["amount_minor"] for c in ocharges if c["status"] == "succeeded")
        out_ref = max(0, succeeded_sum - owed)
        if out_ref > 0:
            orders_needing_refund += 1
            cur = order["currency"]
            outstanding_by_currency[cur] += out_ref
            user_outstanding[order["user_id"]][cur] += out_ref

    extra_charges_all.sort(key=lambda c: c["created_dt"])
    extra_charges_after_culprit.sort(key=lambda c: c["created_dt"])
    print(f"Total extra charges: {len(extra_charges_all)}")
    if extra_charges_all:
        print(f"  Earliest extra charge overall: {extra_charges_all[0]['created_at_utc']} ({extra_charges_all[0]['order_id']}, {extra_charges_all[0]['charge_id']})")
        print(f"  Latest extra charge overall:   {extra_charges_all[-1]['created_at_utc']} ({extra_charges_all[-1]['order_id']}, {extra_charges_all[-1]['charge_id']})")
    first_extra_utc = extra_charges_after_culprit[0]["created_at_utc"]
    print(f"First extra charge >= culprit finished: {first_extra_utc} (order={extra_charges_after_culprit[0]['order_id']}, charge={extra_charges_after_culprit[0]['charge_id']})")
    print(f"Orders needing refund: {orders_needing_refund}")
    print(f"Outstanding refund minor: {dict(outstanding_by_currency)}")

    # Top user
    user_totals = []
    for uid, by_cur in user_outstanding.items():
        cny = Decimal(by_cur.get("CNY", 0))
        usd = Decimal(by_cur.get("USD", 0))
        total_cny = cny + usd * Decimal("7.10")
        user_totals.append((total_cny, uid, dict(by_cur)))
    user_totals.sort(reverse=True)
    print("Top 5 users by outstanding CNY equiv:")
    for tot, uid, by_cur in user_totals[:5]:
        print(f"  {uid}: exact={tot}, rounded={int(tot.quantize(Decimal('1'), rounding=ROUND_HALF_UP))}, breakdown={by_cur}")

    top_tot, top_uid, _ = user_totals[0]
    top_cny_rounded = int(top_tot.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    # 5. Gateway 502 in window
    gw_re = re.compile(r'\[([^\]]+)\]\s+"(\S+)\s+(\S+)\s+[^"]+"\s+(\d{3})\s+')
    gw_502 = 0
    with open(DATA_DIR / "logs" / "gateway-access.log", encoding="utf-8") as f:
        for line in f:
            m = gw_re.search(line)
            if not m:
                continue
            ts_str, method, path, status = m.groups()
            if method == "POST" and path == "/api/v2/checkout" and status == "502":
                dt = datetime.strptime(ts_str, "%d/%b/%Y:%H:%M:%S").replace(tzinfo=CST).astimezone(timezone.utc)
                if t_start <= dt < t_end:
                    gw_502 += 1
    print(f"Gateway POST /api/v2/checkout 502 in window: {gw_502}")

    # 6. payment-svc charge.result stats
    before_durations = []
    during_durations = []
    during_timeouts = 0
    dur_re = re.compile(r"duration_ms=(\d+)")
    res_re = re.compile(r"result=(\S+)")
    with open(DATA_DIR / "logs" / "payment-svc.log", encoding="utf-8") as f:
        for line in f:
            if "event=charge.result" not in line:
                continue
            ts_str = line.split(" ", 1)[0]
            dt = parse_utc(ts_str)
            dur = int(dur_re.search(line).group(1))
            res = res_re.search(line).group(1)
            if t_before_start <= dt < t_start:
                before_durations.append(dur)
            elif t_start <= dt < t_end:
                during_durations.append(dur)
                if res == "timeout":
                    during_timeouts += 1

    before_p95 = nearest_rank_p95(before_durations)
    during_p95 = nearest_rank_p95(during_durations)
    during_timeout_pct = round(100.0 * during_timeouts / len(during_durations), 1)
    print(f"before_p95_ms ({len(before_durations)} events): {before_p95}")
    print(f"during_p95_ms ({len(during_durations)} events): {during_p95}, timeouts={during_timeouts} ({during_timeout_pct}%)")

    answers = {
        "culprit_deploy_id": culprit_id,
        "mitigation_deploy_id": mitigation_id,
        "first_extra_charge_utc": first_extra_utc,
        "orders_needing_refund": orders_needing_refund,
        "outstanding_refund_minor": {
            "CNY": outstanding_by_currency.get("CNY", 0),
            "USD": outstanding_by_currency.get("USD", 0),
        },
        "top_user": {
            "user_id": top_uid,
            "outstanding_cny_minor": top_cny_rounded,
        },
        "gateway_checkout_502_in_window": gw_502,
        "charge_result_stats": {
            "before_p95_ms": before_p95,
            "during_p95_ms": during_p95,
            "during_timeout_rate_pct": during_timeout_pct,
        },
    }

    with open(OUT_DIR / "answers.json", "w", encoding="utf-8") as f:
        json.dump(answers, f, indent=2)
        f.write("\n")
    print("Wrote answers.json")


if __name__ == "__main__":
    main()
