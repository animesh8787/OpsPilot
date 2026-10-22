"""OpsPilot HTTP API: Alertmanager webhook, health, metrics, and dev helpers."""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.agent import Agent
from app.config import get_settings
from app.db import Store
from app.incidents import Commands, IncidentService
from app.llm.factory import make_provider
from app.logging import setup_logging
from app.mcp_client import ToolHub
from app.notifier import SlackNotifier

log = logging.getLogger("opspilot")


@dataclass
class Deps:
    service: IncidentService
    commands: Commands
    dry_run: bool


async def _build_real(stack: list) -> Deps:
    s = get_settings()
    hub = ToolHub()
    await hub.start()
    stack.append(hub.close)
    agent = Agent(make_provider(s), hub, s.agent_max_tool_calls, s.agent_timeout_s)
    store = Store(s.database_url)
    live = bool(s.slack_bot_token and s.slack_app_token)
    client = None
    if live:
        from slack_sdk.web.async_client import AsyncWebClient

        client = AsyncWebClient(token=s.slack_bot_token)
    service = IncidentService(
        store, agent, SlackNotifier(client, s.slack_channel), s.prometheus_url
    )
    commands = Commands(service)
    if live:
        from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

        from app.slack_bot import build_app

        handler = AsyncSocketModeHandler(
            build_app(s.slack_bot_token, service, commands), s.slack_app_token
        )
        await handler.connect_async()
        stack.append(handler.close_async)
        log.info("slack socket mode connected")
    else:
        log.warning("SLACK tokens not set: running in dry-run mode (messages are logged only)")
    return Deps(service, commands, dry_run=not live)


def create_app(deps: Deps | None = None) -> FastAPI:
    setup_logging()
    closers: list = []
    tasks: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.deps = deps or await _build_real(closers)
        yield
        for close in reversed(closers):
            await close()

    app = FastAPI(title="OpsPilot", lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/alerts", status_code=202)
    async def alerts(request: Request) -> dict:
        payload = await request.json()
        if not isinstance(payload.get("alerts"), list):
            raise HTTPException(422, "expected an Alertmanager webhook payload with an alerts list")
        log.info(
            "alert webhook received", extra={"extra_fields": {"alerts": len(payload["alerts"])}}
        )
        # triage can take many seconds: answer Alertmanager immediately, work in the background
        task = asyncio.create_task(app.state.deps.service.handle_alerts(payload))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {"accepted": len(payload["alerts"])}

    def _view(i) -> dict:
        t = i.triage
        return {
            "id": i.id,
            "alertname": i.alertname,
            "service": i.service,
            "severity": i.severity,
            "status": i.status,
            "alert_count": i.alert_count,
            "created_at": i.created_at.isoformat(),
            "acknowledged_at": i.acknowledged_at and i.acknowledged_at.isoformat(),
            "resolved_at": i.resolved_at and i.resolved_at.isoformat(),
            "summary": t.summary if t else None,
            "likely_cause": t.likely_cause if t else None,
            "evidence": t.evidence if t else [],
            "runbook_url": t.runbook_url if t else None,
        }

    @app.get("/incidents")
    def incidents() -> list[dict]:
        return [_view(i) for i in app.state.deps.service.store.list_all()]

    @app.post("/incidents/{incident_id}/{action}")
    async def act(incident_id: int, action: str, user: str = "http") -> dict:
        svc = app.state.deps.service
        if action not in ("ack", "resolve"):
            raise HTTPException(404, "action must be ack or resolve")
        inc = await (svc.ack if action == "ack" else svc.resolve)(incident_id, user)
        if inc is None:
            raise HTTPException(409, "incident not found or already in that state")
        return _view(inc)

    @app.post("/dev/command/{name}")
    async def dev_command(name: str, request: Request) -> dict:
        """Run a slash command without Slack. Only available in dry-run mode."""
        d: Deps = app.state.deps
        if not d.dry_run:
            raise HTTPException(404)
        text = (await request.body()).decode()
        fn = {
            "opsstatus": lambda: d.commands.status(),
            "incident": lambda: d.commands.incident(text),
            "ask": lambda: d.commands.ask(text),
        }.get(name)
        if fn is None:
            raise HTTPException(404, "unknown command")
        fallback, blocks = await fn()
        return {"text": fallback, "blocks": blocks}

    return app


app = create_app()
