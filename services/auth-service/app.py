import time, random, json, os
from datetime import datetime, timezone

SERVICE = os.getenv("SERVICE_NAME", "auth-service")
LEVEL   = os.getenv("LOG_LEVEL", "INFO")

EVENTS = [
    ("INFO",  "User login successful",          lambda: {"user_id": f"u-{random.randint(1000,9999)}", "latency_ms": round(random.uniform(10, 80), 2)}),
    ("INFO",  "Token validation passed",         lambda: {"request_id": f"r-{random.randint(10000,99999)}", "latency_ms": round(random.uniform(5, 30), 2)}),
    ("WARN",  "Login attempt with expired token",lambda: {"user_id": f"u-{random.randint(1000,9999)}", "attempt": random.randint(1, 3)}),
    ("ERROR", "Authentication backend timeout",  lambda: {"user_id": f"u-{random.randint(1000,9999)}", "latency_ms": 5000, "retry": True}),
    ("INFO",  "Session created",                 lambda: {"session_id": f"s-{random.randint(1000,9999)}", "latency_ms": round(random.uniform(5, 20), 2)}),
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
    time.sleep(random.uniform(0.5, 3.0))
