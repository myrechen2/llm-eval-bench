import csv
import json
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


def main():
    orders = {}
    with open(DATA_DIR / "orders.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["amount_minor"] = int(r["amount_minor"])
            orders[r["order_id"]] = r

    charges_by_order = defaultdict(list)
    with open(DATA_DIR / "provider_charges.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["amount_minor"] = int(r["amount_minor"])
            charges_by_order[r["order_id"]].append(r)

    # Check payment_failed orders that have succeeded/refunded charges
    pf_with_succ = []
    for oid, o in orders.items():
        if o["status"] != "paid":
            clist = [c for c in charges_by_order[oid] if c["status"] in ("succeeded", "refunded")]
            if clist:
                pf_with_succ.append((oid, o["created_at_utc"], o["status"], len(clist), clist))
    pf_with_succ.sort(key=lambda x: x[1])
    print(f"Non-paid orders with succeeded/refunded charges: {len(pf_with_succ)}")
    for item in pf_with_succ[:5]:
        print(" ", item[0], item[1], item[2], "n_charges=", item[3], [c["created_at_utc"] for c in item[4]])

    # Check charge timestamp ties within same order
    ties = []
    for oid, clist in charges_by_order.items():
        succ = [c for c in clist if c["status"] in ("succeeded", "refunded")]
        if len(succ) > 1:
            ts = [c["created_at_utc"] for c in succ]
            if len(ts) != len(set(ts)):
                ties.append((oid, succ))
    print(f"Orders with duplicate created_at_utc among succeeded/refunded charges: {len(ties)}")
    for oid, succ in ties:
        print(" ", oid, [(c["charge_id"], c["created_at_utc"], c["status"], c["amount_minor"]) for c in succ])

    # Check O0314-003214..O0314-003223 in charges & payment-svc.log
    print("\n=== Orders O0314-003214..003223 ===")
    for num in range(3214, 3224):
        oid = f"O0314-00{num}"
        print(oid, orders[oid]["status"], orders[oid]["amount_minor"], "charges:", [(c["charge_id"], c["status"], c["created_at_utc"]) for c in charges_by_order[oid]])

    # Check non-incident checkout 502s (why did 60 happen around 22:40Z..00:05Z?)
    gw_re = re.compile(
        r'^(\S+) - (\S+) \[(\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2})\] "(\S+) (\S+) ([^"]+)" (\d+) rt=(\S+) upstream=(\S+) trace=(\S+)$'
    )
    all_502_by_hour = defaultdict(Counter)
    with open(DATA_DIR / "logs/gateway-access.log", encoding="utf-8") as f:
        for line in f:
            m = gw_re.match(line.rstrip("\r\n"))
            if not m:
                continue
            ip, uid, dt_str, method, path, proto, status_str, rt_str, upstream, trace = m.groups()
            if status_str == "502":
                dt_utc = datetime.strptime(dt_str, "%d/%b/%Y:%H:%M:%S").replace(tzinfo=CST).astimezone(timezone.utc)
                all_502_by_hour[dt_utc.strftime("%Y-%m-%d %H:00Z")][upstream] += 1
    print("\n=== All gateway 502s by hour (UTC) and upstream ===")
    for h in sorted(all_502_by_hour):
        print(f"  {h}: {dict(all_502_by_hour[h])}")

    # Check if any checkout 502 happens between 06:33:20Z and 06:40:00Z or 08:02:30Z and 09:00:00Z
    print("\n=== Checkout 502s on 2026-03-14 ===")
    with open(DATA_DIR / "logs/gateway-access.log", encoding="utf-8") as f:
        c502_0314 = []
        for line in f:
            m = gw_re.match(line.rstrip("\r\n"))
            if not m:
                continue
            ip, uid, dt_str, method, path, proto, status_str, rt_str, upstream, trace = m.groups()
            if method == "POST" and path == "/api/v2/checkout" and status_str == "502":
                dt_utc = datetime.strptime(dt_str, "%d/%b/%Y:%H:%M:%S").replace(tzinfo=CST).astimezone(timezone.utc)
                if dt_utc >= parse_utc("2026-03-14T00:00:00Z"):
                    c502_0314.append((dt_utc.isoformat(), rt_str))
    print("Total on 2026-03-14:", len(c502_0314))
    print("First 5:", c502_0314[:5])
    print("Last 5:", c502_0314[-5:])


if __name__ == "__main__":
    main()
