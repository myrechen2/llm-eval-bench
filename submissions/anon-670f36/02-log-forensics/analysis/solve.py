import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

DATA_DIR = Path("tasks/02-log-forensics/data")
OUT_DIR = Path("submissions/anon-670f36/02-log-forensics")
CST = timezone(timedelta(hours=8))


def parse_utc(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def nearest_rank_p95(values: list[int]) -> int:
    s = sorted(values)
    idx = math.ceil(0.95 * len(s)) - 1
    return s[idx]


def main() -> None:
    # 1. Load deploys
    with open(DATA_DIR / "deploys.csv", newline="", encoding="utf-8") as f:
        deploys = {row["deploy_id"]: row for row in csv.DictReader(f)}

    culprit_id = "DEP-7731"
    mitigation_id = "DEP-7740"
    culprit_dt = parse_utc(deploys[culprit_id]["finished_at_utc"])
    mitigation_dt = parse_utc(deploys[mitigation_id]["finished_at_utc"])
    before_dt = culprit_dt - timedelta(hours=2)

    # 2. Load orders and provider charges
    orders: dict[str, dict] = {}
    with open(DATA_DIR / "orders.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["amount_minor"] = int(row["amount_minor"])
            orders[row["order_id"]] = row

    charges_by_order: dict[str, list[dict]] = defaultdict(list)
    with open(DATA_DIR / "provider_charges.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["amount_minor"] = int(row["amount_minor"])
            row["created_dt"] = parse_utc(row["created_at_utc"])
            charges_by_order[row["order_id"]].append(row)

    # 3. Extra charges & outstanding refunds per docs/finance-reconciliation.md
    extra_charges_after_culprit = []
    orders_needing_refund = 0
    outstanding_by_currency: Counter[str] = Counter()
    user_outstanding_by_currency: dict[str, Counter[str]] = defaultdict(Counter)
    orders_with_refunded_charges = 0
    paid_undercharged = []

    for oid, order in orders.items():
        owed = order["amount_minor"] if order["status"] == "paid" else 0
        clist = sorted(
            charges_by_order.get(oid, []),
            key=lambda c: (c["created_dt"], c["charge_id"]),
        )

        running = 0
        for c in clist:
            if c["status"] in ("succeeded", "refunded"):
                running += c["amount_minor"]
                if running > owed and c["created_dt"] >= culprit_dt:
                    extra_charges_after_culprit.append(c)

        succeeded_sum = sum(c["amount_minor"] for c in clist if c["status"] == "succeeded")
        if any(c["status"] == "refunded" for c in clist):
            orders_with_refunded_charges += 1
        if succeeded_sum < owed:
            paid_undercharged.append((oid, owed, succeeded_sum))

        outstanding = max(0, succeeded_sum - owed)
        if outstanding > 0:
            orders_needing_refund += 1
            cur = order["currency"]
            outstanding_by_currency[cur] += outstanding
            user_outstanding_by_currency[order["user_id"]][cur] += outstanding

    extra_charges_after_culprit.sort(key=lambda c: (c["created_dt"], c["charge_id"]))
    first_extra_charge_utc = extra_charges_after_culprit[0]["created_at_utc"]

    # Top user in CNY minor (1 USD = 7.10 CNY)
    best_user = None
    best_cny_exact = Decimal(-1)
    best_cny_rounded = -1
    for uid, cur_map in user_outstanding_by_currency.items():
        exact = Decimal(cur_map["CNY"]) + Decimal(cur_map["USD"]) * Decimal("7.10")
        rounded = int(exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if exact > best_cny_exact:
            best_cny_exact = exact
            best_cny_rounded = rounded
            best_user = uid

    # 4. Gateway access log (Asia/Shanghai UTC+8 -> UTC)
    gw_re = re.compile(
        r'^(\S+) - (\S+) \[(\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2})\] '
        r'"(\S+) (\S+) ([^"]+)" (\d+) rt=(\S+) upstream=(\S+) trace=(\S+)$'
    )
    gw_checkout_502_in_window = 0
    with open(DATA_DIR / "logs/gateway-access.log", encoding="utf-8") as f:
        for line in f:
            m = gw_re.match(line.rstrip("\r\n"))
            if not m:
                raise ValueError(f"Unmatched gateway line: {line}")
            _, _, dt_str, method, path, _, status_str, _, _, _ = m.groups()
            if method == "POST" and path == "/api/v2/checkout" and status_str == "502":
                dt_utc = (
                    datetime.strptime(dt_str, "%d/%b/%Y:%H:%M:%S")
                    .replace(tzinfo=CST)
                    .astimezone(timezone.utc)
                )
                if culprit_dt <= dt_utc < mitigation_dt:
                    gw_checkout_502_in_window += 1

    # 5. payment-svc.log charge.result stats & mechanism verification
    line_re = re.compile(r"^(\S+)\s+(\w+)\s+\[payment-svc\s+(\S+)\]\s+(.*)$")
    kv_re = re.compile(r"(\w+)=(\S+)")

    before_durations: list[int] = []
    during_durations: list[int] = []
    during_timeouts = 0

    retry_same_idem = 0
    retry_diff_idem = 0
    order_first_idem: dict[tuple[str, str], str] = {}

    with open(DATA_DIR / "logs/payment-svc.log", encoding="utf-8") as f:
        for line in f:
            m = line_re.match(line.rstrip("\r\n"))
            if not m:
                raise ValueError(f"Unmatched payment-svc line: {line}")
            ts_str, _, ver, rest = m.groups()
            dt = parse_utc(ts_str)
            kvs = dict(kv_re.findall(rest))
            ev = kvs.get("event")
            if ev == "charge.request":
                key = (kvs["order"], kvs["trace"])
                attempt = int(kvs["attempt"])
                if attempt == 1:
                    order_first_idem[key] = kvs["idem_key"]
                else:
                    if order_first_idem.get(key) == kvs["idem_key"]:
                        retry_same_idem += 1
                    else:
                        retry_diff_idem += 1
            elif ev == "charge.result":
                dur = int(kvs["duration_ms"])
                res = kvs["result"]
                if before_dt <= dt < culprit_dt:
                    before_durations.append(dur)
                elif culprit_dt <= dt < mitigation_dt:
                    during_durations.append(dur)
                    if res == "timeout":
                        during_timeouts += 1

    before_p95_ms = nearest_rank_p95(before_durations)
    during_p95_ms = nearest_rank_p95(during_durations)
    during_timeout_rate_pct = round(during_timeouts * 100.0 / len(during_durations), 1)

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
            "user_id": best_user,
            "outstanding_cny_minor": best_cny_rounded,
        },
        "gateway_checkout_502_in_window": gw_checkout_502_in_window,
        "charge_result_stats": {
            "before_p95_ms": before_p95_ms,
            "during_p95_ms": during_p95_ms,
            "during_timeout_rate_pct": during_timeout_rate_pct,
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "answers.json", "w", encoding="utf-8") as f:
        json.dump(answers, f, indent=2)
        f.write("\n")

    print("Wrote answers.json:")
    print(json.dumps(answers, indent=2))
    print("\nSanity checks:")
    print(f"  orders_with_refunded_charges={orders_with_refunded_charges}, paid_undercharged={paid_undercharged}")
    print(f"  retries reusing idem_key={retry_same_idem}, retries with NEW idem_key={retry_diff_idem}")
    print(f"  extra_charges_after_culprit={len(extra_charges_after_culprit)}")
    print(f"  before_n={len(before_durations)}, during_n={len(during_durations)}, during_timeouts={during_timeouts}")


if __name__ == "__main__":
    main()
