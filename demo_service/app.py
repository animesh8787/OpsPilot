"""Demo 'checkout' service: Prometheus metrics, chaos injection, structured JSON logs."""

import asyncio
import json
import os
import random
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel

SERVICE = "checkout"
LOG_FILE = Path(os.getenv("LOG_FILE", "data/demo_service.log"))
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

REQS = Counter("http_requests_total", "HTTP requests", ["path", "status"])
LAT = Histogram(
    "http_request_duration_seconds",
    "HTTP latency",
    ["path"],
    buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)

ERROR_MESSAGES = [
    "db connection pool exhausted: timeout after 5s waiting for connection (pool_size=10)",
    "payment gateway returned 502 for order {order}",
    "upstream inventory-service timed out after 3000ms",
]

chaos = {"error_rate": 0.0, "latency_ms": 0}
app = FastAPI(title="demo checkout service")


def log(level: str, msg: str, **fields: object) -> None:
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": level,
        "service": SERVICE,
        "msg": msg,
        **fields,
    }
    line = json.dumps(rec)
    print(line, flush=True)
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")


class Chaos(BaseModel):
    error_rate: float = 0.0  # 0..1
    latency_ms: int = 0


@app.get("/chaos")
def get_chaos() -> dict:
    return chaos


@app.post("/chaos")
def set_chaos(c: Chaos) -> dict:
    if not 0 <= c.error_rate <= 1 or c.latency_ms < 0:
        raise HTTPException(422, "error_rate must be in [0,1], latency_ms >= 0")
    chaos.update(c.model_dump())
    log("WARN", "chaos config changed", **chaos)
    return chaos


@app.get("/checkout")
async def checkout() -> dict:
    start = time.perf_counter()
    order = f"ord-{random.randint(1000, 9999)}"
    await asyncio.sleep(random.uniform(0.005, 0.04) + chaos["latency_ms"] / 1000)
    status = 500 if random.random() < chaos["error_rate"] else 200
    dur = time.perf_counter() - start
    REQS.labels("/checkout", str(status)).inc()
    LAT.labels("/checkout").observe(dur)
    if status == 500:
        log("ERROR", random.choice(ERROR_MESSAGES).format(order=order), order=order, status=500)
        raise HTTPException(500, "checkout failed")
    if dur > 0.5:
        log("WARN", f"slow checkout {dur * 1000:.0f}ms", order=order, duration_ms=int(dur * 1000))
    else:
        log("INFO", "checkout ok", order=order, duration_ms=int(dur * 1000))
    return {"order": order, "status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
