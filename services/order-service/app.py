import time, random, json, os
from datetime import datetime, timezone

SERVICE = os.getenv("SERVICE_NAME", "order-service")

EVENTS = [
    ("INFO",  "Order placed successfully",       lambda: {"order_id": f"ord-{random.randint(10000,99999)}", "amount_usd": round(random.uniform(5, 500), 2), "latency_ms": round(random.uniform(50, 200), 2)}),
    ("INFO",  "Payment confirmed",               lambda: {"order_id": f"ord-{random.randint(10000,99999)}", "latency_ms": round(random.uniform(100, 400), 2)}),
    ("WARN",  "Inventory low for SKU",           lambda: {"sku": f"SKU-{random.randint(100,999)}", "quantity_remaining": random.randint(1, 5)}),
    ("ERROR", "Payment gateway connection lost", lambda: {"order_id": f"ord-{random.randint(10000,99999)}", "latency_ms": 8000, "gateway": "stripe"}),
    ("INFO",  "Order dispatched to fulfillment", lambda: {"order_id": f"ord-{random.randint(10000,99999)}", "warehouse": random.choice(["WH-NORTH", "WH-SOUTH", "WH-EAST"])}),
    ("ERROR", "Duplicate order ID rejected",     lambda: {"order_id": f"ord-{random.randint(10000,99999)}", "http_status": 409}),
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
    time.sleep(random.uniform(0.3, 2.5))
