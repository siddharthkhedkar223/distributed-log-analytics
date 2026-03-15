import time, random, json, os
from datetime import datetime, timezone

SERVICE = os.getenv("SERVICE_NAME", "inventory-service")

EVENTS = [
    ("WARN",  "Stock threshold breached",        lambda: {"sku": f"SKU-{random.randint(100,999)}", "quantity": random.randint(1, 10), "threshold": 10}),
    ("INFO",  "Inventory replenishment triggered",lambda: {"sku": f"SKU-{random.randint(100,999)}", "reorder_qty": random.randint(50, 200)}),
    ("ERROR", "DB write timeout on stock update", lambda: {"sku": f"SKU-{random.randint(100,999)}", "latency_ms": 6000, "db_host": "postgres-01"}),
    ("WARN",  "Price sync lag detected",          lambda: {"sku": f"SKU-{random.randint(100,999)}", "lag_seconds": round(random.uniform(30, 120), 1)}),
    ("INFO",  "Cycle count completed for zone",   lambda: {"zone": random.choice(["A", "B", "C", "D"]), "discrepancies": random.randint(0, 3)}),
]

def emit(level, message, extra):
    record = {
        "@timestamp": datetime.now(timezone.utc).isoformat(),
        "level":     level,
        "service":   SERVICE,
        "message":   message,
        **extra
    }
    print(json.dumps(record), flush=True)

while True:
    level, msg, extra_fn = random.choice(EVENTS)
    emit(level, msg, extra_fn())
    time.sleep(random.uniform(1.0, 5.0))
