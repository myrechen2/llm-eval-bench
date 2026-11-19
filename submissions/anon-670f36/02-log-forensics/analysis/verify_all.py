import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

DATA_DIR = Path("tasks/02-log-forensics/data")
CST = timezone(timedelta(hours=8))


def parse_utc(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def main():
    # 1. Check CSV uniqueness & edge cases
    orders = {}
    dup_orders = 0
    with open(DATA_DIR / "orders.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            oid = r["order_id"]
            if oid in orders:
                dup_orders += 1
            r["amount_minor"] = int(r["amount_minor"])
            r["dt"] = parse_utc(r["created_at_utc"])
            orders[oid] = r
    print(f"Orders: {len(orders)}, duplicates: {dup_orders}")

    charges = {}
    dup_charges = 0
    charges_by_order = defaultdict(list)
    with open(DATA_DIR / "provider_charges.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cid = r["charge_id"]
            if cid in charges:
                dup_charges += 1
            r["amount_minor"] = int(r["amount_minor"])
            r["dt"] = parse_utc(r["created_at_utc"])
            charges[cid] = r
            charges_by_order[r["order_id"]].append(r)
    print(f"Charges: {len(charges)}, duplicates: {dup_charges}")

    # Check split orders
    split_anomalies = []
    for oid, o in orders.items():
        if o["payment_method"] == "split":
            clist = charges_by_order[oid]
            succ = sum(c["amount_minor"] for c in clist if c["status"] in ("succeeded", "refunded"))
            owed = o["amount_minor"] if o["status"] == "paid" else 0
            if succ != owed:
                split_anomalies.append((oid, o, clist))
    print(f"Split order anomalies (succ+ref != owed): {len(split_anomalies)}")
    for item in split_anomalies:
        print(" ", item)

    # Check orders with outstanding refund > 0
    refund_orders = []
    for oid, o in orders.items():
        owed = o["amount_minor"] if o["status"] == "paid" else 0
        clist = charges_by_order[oid]
        succ_only = sum(c["amount_minor"] for c in clist if c["status"] == "succeeded")
        out_ref = max(0, succ_only - owed)
        if out_ref > 0:
            refund_orders.append((oid, o["created_at_utc"], o["user_id"], o["currency"], out_ref, o["status"]))
    refund_orders.sort(key=lambda x: x[1])
    print(f"Refund orders count: {len(refund_orders)}")
    print("Earliest 3 refund orders:", refund_orders[:3])
    print("Latest 3 refund orders:", refund_orders[-3:])

    # Check exact Decimal for top_user
    user_cur = defaultdict(lambda: Counter())
    for oid, _, uid, cur, out_ref, _ in refund_orders:
        user_cur[uid][cur] += out_ref
    multi_cur_users = [uid for uid, cm in user_cur.items() if len(cm) > 1]
    print("Users with outstanding refunds in >1 currency:", multi_cur_users)
    user_ranked = []
    for uid, cm in user_cur.items():
        exact = Decimal(cm["CNY"]) + Decimal(cm["USD"]) * Decimal("7.10")
        rounded = int(exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        user_ranked.append((exact, rounded, uid, dict(cm)))
    user_ranked.sort(reverse=True)
    print("Top 5 users (Decimal):", user_ranked[:5])

    # 2. Check payment-svc.log around O0314-003214..O0314-003225 and around 08:02:20..08:02:40
    kv_re = re.compile(r"(\w+)=(\S+)")
    line_re = re.compile(r"^(\S+)\s+(\w+)\s+\[payment-svc\s+(\S+)\]\s+(.*)$")
    t_before = parse_utc("2026-03-14T04:40:00Z")
    t_culprit = parse_utc("2026-03-14T06:40:00Z")
    t_mit = parse_utc("2026-03-14T08:02:30Z")

    print("\n=== Payment-svc around 06:39:50..06:40:50 ===")
    with open(DATA_DIR / "logs/payment-svc.log", encoding="utf-8") as f:
        pay_lines = [l.rstrip("\r\n") for l in f]

    before_rows = []
    during_rows = []
    exact_boundary_pay = []
    timeouts_by_ver_and_period = Counter()

    for line in pay_lines:
        m = line_re.match(line)
        if not m:
            continue
        ts_str, level, ver, rest = m.groups()
        dt = parse_utc(ts_str)
        kvs = dict(kv_re.findall(rest))
        ev = kvs.get("event")
        if parse_utc("2026-03-14T06:39:50Z") <= dt <= parse_utc("2026-03-14T06:40:50Z") and ev != "health":
            print(" ", line)
        if ev == "charge.result":
            dur = int(kvs["duration_ms"])
            res = kvs["result"]
            if dt in (t_before, t_culprit, t_mit):
                exact_boundary_pay.append(line)
            if t_before <= dt < t_culprit:
                before_rows.append((dt, ver, res, dur))
            elif t_culprit <= dt < t_mit:
                during_rows.append((dt, ver, res, dur))
                timeouts_by_ver_and_period[(ver, res)] += 1

    print("Exact boundary charge.result lines:", exact_boundary_pay)
    print("During results by (ver, res):", timeouts_by_ver_and_period)

    # Check duration distribution before and during
    before_durs = sorted(r[3] for r in before_rows)
    during_durs = sorted(r[3] for r in during_rows)
    print("Before n=", len(before_durs), "p95 idx=", math.ceil(0.95 * len(before_durs)), "val=", before_durs[math.ceil(0.95 * len(before_durs)) - 1])
    print("  neighbors around p95:", before_durs[math.ceil(0.95 * len(before_durs)) - 3 : math.ceil(0.95 * len(before_durs)) + 2])
    print("During n=", len(during_durs), "p95 idx=", math.ceil(0.95 * len(during_durs)), "val=", during_durs[math.ceil(0.95 * len(during_durs)) - 1])
    print("  count of >=3000ms in during:", sum(1 for d in during_durs if d >= 3000))
    during_to = sum(1 for r in during_rows if r[2] == "timeout")
    print(f"During timeouts={during_to}/{len(during_rows)} = {during_to*100/len(during_rows):.6f}% -> round 1dp = {round(during_to*100/len(during_rows), 1)}")

    # Check timeout rate over time (every 10 min from 05:30 to 09:00) to show PayNova latency timeline!
    print("\n=== PayNova latency & timeout rate by 10-min bucket (UTC) ===")
    buckets = defaultdict(list)
    for line in pay_lines:
        m = line_re.match(line)
        if not m:
            continue
        ts_str, level, ver, rest = m.groups()
        dt = parse_utc(ts_str)
        kvs = dict(kv_re.findall(rest))
        if kvs.get("event") == "charge.result":
            if parse_utc("2026-03-14T05:30:00Z") <= dt < parse_utc("2026-03-14T09:00:00Z"):
                b = dt.replace(minute=(dt.minute // 10) * 10, second=0, microsecond=0)
                buckets[b].append((kvs["result"], int(kvs["duration_ms"])))
    for b in sorted(buckets):
        vals = buckets[b]
        n = len(vals)
        to = sum(1 for r, _ in vals if r == "timeout")
        durs = sorted(d for _, d in vals)
        p95 = durs[math.ceil(0.95 * n) - 1]
        print(f"  {b.strftime('%H:%M')}Z: n={n:4d}, timeouts={to:3d} ({to*100/n:5.1f}%), p95={p95}ms")

    # 3. Check gateway-access.log checkout paths, query strings, and 502s outside vs inside
    gw_re = re.compile(
        r'^(\S+) - (\S+) \[(\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2})\] "(\S+) (\S+) ([^"]+)" (\d+) rt=(\S+) upstream=(\S+) trace=(\S+)$'
    )
    checkout_paths = Counter()
    gw_checkout_502_in = 0
    gw_checkout_502_exact_bound = []
    gw_checkout_502_by_hour = Counter()
    gw_checkout_502_rts_in = []
    gw_checkout_502_rts_out = []

    with open(DATA_DIR / "logs/gateway-access.log", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            m = gw_re.match(line)
            if not m:
                continue
            ip, uid, dt_str, method, path, proto, status_str, rt_str, upstream, trace = m.groups()
            status = int(status_str)
            rt = float(rt_str)
            if "checkout" in path:
                checkout_paths[(method, path)] += 1
            if method == "POST" and path == "/api/v2/checkout" and status == 502:
                dt_utc = datetime.strptime(dt_str, "%d/%b/%Y:%H:%M:%S").replace(tzinfo=CST).astimezone(timezone.utc)
                if dt_utc in (t_culprit, t_mit):
                    gw_checkout_502_exact_bound.append((dt_utc.isoformat(), line))
                if t_culprit <= dt_utc < t_mit:
                    gw_checkout_502_in += 1
                    gw_checkout_502_rts_in.append(rt)
                else:
                    gw_checkout_502_rts_out.append(rt)
                gw_checkout_502_by_hour[dt_utc.strftime("%Y-%m-%d %H:00Z")] += 1

    print("\n=== Gateway checkout details ===")
    print("Checkout paths:", checkout_paths)
    print("Exact boundary 502s:", gw_checkout_502_exact_bound)
    print(f"502 in [06:40:00Z, 08:02:30Z): {gw_checkout_502_in}")
    print("  rt values in window (Counter):", Counter(gw_checkout_502_rts_in).most_common(10))
    print("  rt values outside window (min/max):", min(gw_checkout_502_rts_out), max(gw_checkout_502_rts_out))
    print("  all checkout 502s by hour (UTC):", sorted(gw_checkout_502_by_hour.items()))

    # 4. Check all 502s around 06:30..07:30 by service to disprove keepalive / order-svc v3.9.0!
    print("\n=== Gateway 502 rate by 10-min bucket (06:00Z..08:30Z) ===")
    gw_all_buckets = defaultdict(Counter)
    with open(DATA_DIR / "logs/gateway-access.log", encoding="utf-8") as f:
        for line in f:
            m = gw_re.match(line.rstrip("\r\n"))
            if not m:
                continue
            ip, uid, dt_str, method, path, proto, status_str, rt_str, upstream, trace = m.groups()
            dt_utc = datetime.strptime(dt_str, "%d/%b/%Y:%H:%M:%S").replace(tzinfo=CST).astimezone(timezone.utc)
            if parse_utc("2026-03-14T06:00:00Z") <= dt_utc < parse_utc("2026-03-14T08:30:00Z"):
                b = dt_utc.replace(minute=(dt_utc.minute // 10) * 10, second=0, microsecond=0)
                status = int(status_str)
                gw_all_buckets[b]["total"] += 1
                if status == 502:
                    gw_all_buckets[b][f"502_{upstream}"] += 1
                if method == "POST" and path == "/api/v2/checkout":
                    gw_all_buckets[b]["checkout_total"] += 1
                    if status == 502:
                        gw_all_buckets[b]["checkout_502"] += 1
    for b in sorted(gw_all_buckets):
        c = gw_all_buckets[b]
        print(f"  {b.strftime('%H:%M')}Z: total={c['total']:4d}, checkout={c['checkout_total']:3d}, checkout_502={c['checkout_502']:2d}, 502_order={c['502_order-svc']:2d}, 502_catalog={c['502_catalog-svc']:2d}, 502_cart={c['502_cart-svc']:2d}")


if __name__ == "__main__":
    main()
