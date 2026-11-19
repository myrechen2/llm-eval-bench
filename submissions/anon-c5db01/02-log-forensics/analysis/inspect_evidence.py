import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

DATA_DIR = Path("tasks/02-log-forensics/data")


def inspect_orders(target_orders: set[str]):
    print("=== ORDERS ===")
    with (DATA_DIR / "orders.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["order_id"] in target_orders:
                print("ORDER:", row)

    print("\n=== PROVIDER CHARGES ===")
    with (DATA_DIR / "provider_charges.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["order_id"] in target_orders:
                print("CHARGE:", row)

    print("\n=== ORDER-SVC LOGS ===")
    traces = set()
    with (DATA_DIR / "logs/order-svc.jsonl").open(encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            if obj.get("order_id") in target_orders:
                print("ORDER-SVC:", line.strip())
                if "trace_id" in obj:
                    traces.add(obj["trace_id"])

    print("\n=== PAYMENT-SVC LOGS ===")
    with (DATA_DIR / "logs/payment-svc.log").open(encoding="utf-8") as f:
        for line in f:
            for oid in target_orders:
                if f"order={oid} " in line:
                    print("PAYMENT-SVC:", line.strip())
                    break

    print("\n=== GATEWAY LOGS (matching traces) ===")
    with (DATA_DIR / "logs/gateway-access.log").open(encoding="utf-8") as f:
        for line in f:
            for tr in traces:
                if f"trace={tr}" in line:
                    print("GATEWAY:", line.strip())
                    break


def check_anomalies():
    # Check all payment-svc events & versions
    events = Counter()
    versions = Counter()
    with (DATA_DIR / "logs/payment-svc.log").open(encoding="utf-8") as f:
        for line in f:
            # e.g. 2026-03-13T22:00:03.674Z INFO  [payment-svc v2.13.4] event=charge.request ...
            lb = line.find("[payment-svc ")
            rb = line.find("]", lb)
            if lb != -1 and rb != -1:
                versions[line[lb + 13 : rb]] += 1
            for tok in line.split():
                if tok.startswith("event="):
                    events[tok.split("=", 1)[1]] += 1
    print("payment-svc versions:", dict(versions))
    print("payment-svc events:", dict(events))

    # Check if any split order has extra charges or outstanding refund
    orders = {}
    with (DATA_DIR / "orders.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            orders[row["order_id"]] = row

    charges_by_order = defaultdict(list)
    with (DATA_DIR / "provider_charges.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            charges_by_order[row["order_id"]].append(row)

    split_issues = []
    for oid, o in orders.items():
        if o["payment_method"] == "split":
            owed = int(o["amount_minor"]) if o["status"] == "paid" else 0
            succ = sum(int(c["amount_minor"]) for c in charges_by_order[oid] if c["status"] == "succeeded")
            if succ != owed:
                split_issues.append((oid, o["status"], owed, succ, len(charges_by_order[oid])))
    print("Split orders with succ != owed:", len(split_issues), split_issues[:5])

    # Find top user U100670 orders
    u_orders = [oid for oid, o in orders.items() if o["user_id"] == "U100670"]
    print("U100670 orders:", u_orders)


if __name__ == "__main__":
    check_anomalies()
    print("\n--- Inspecting specific orders ---")
    inspect_orders({"O0314-001701", "O0314-003221", "O0314-003220", "O0314-003222", "O0314-004068", "O0314-004083"})
