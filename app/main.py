"""OpsPilot API (stub until the agent is wired in Phase 5)."""

import logging

from fastapi import FastAPI, Request

from app.logging import setup_logging

setup_logging()
log = logging.getLogger("opspilot")
app = FastAPI(title="OpsPilot")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/alerts")
async def alerts(request: Request) -> dict:
    payload = await request.json()
    log.info("alert webhook received: %d alerts", len(payload.get("alerts", [])))
    return {"received": len(payload.get("alerts", []))}
