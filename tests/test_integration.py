import time
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app import incidents as incidents_mod
from app.agent import Agent
from app.db import Store
from app.incidents import Commands, IncidentService
from app.llm.mock_provider import MockProvider
from app.main import Deps, create_app
from app.notifier import SlackNotifier
from tests.test_agent import FakeHub

PAYLOAD = {
    "version": "4",
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "HighErrorRate", "service": "checkout", "severity": "critical"},
            "annotations": {"summary": "checkout 5xx ratio above 5%"},
            "startsAt": "2026-10-22T10:00:00Z",
            "fingerprint": "abc123",
        }
    ],
}


@pytest.fixture
def env(tmp_path):
    slack = AsyncMock()
    slack.chat_postMessage.return_value = {"channel": "C123", "ts": "1700000000.000100"}
    store = Store(f"sqlite:///{tmp_path}/test.db")
    svc = IncidentService(
        store, Agent(MockProvider(), FakeHub()), SlackNotifier(slack, "#incidents"), "http://prom"
    )
    return slack, store, svc


def _wait(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _texts(blocks):
    return " ".join(b["text"]["text"] for b in blocks if b["type"] == "section")


def test_webhook_to_slack_message_then_dedupe_ack_resolve(env):
    slack, store, svc = env
    with TestClient(create_app(Deps(svc, Commands(svc), dry_run=True))) as c:
        assert c.post("/alerts", json=PAYLOAD).status_code == 202
        assert _wait(lambda: slack.chat_postMessage.await_count == 1)

        # incident stored + message shape
        (inc,) = c.get("/incidents").json()
        assert inc["status"] == "open" and inc["severity"] == "critical"
        kw = slack.chat_postMessage.await_args.kwargs
        assert kw["channel"] == "#incidents" and "HighErrorRate" in kw["text"]
        blocks = kw["blocks"]
        assert blocks[0]["type"] == "header"
        body = _texts(blocks)
        assert "0.41" in body  # evidence quoted from tool output
        assert "db connection pool exhausted" in body
        assert "http://x/high-error-rate.md" in body  # runbook link
        actions = next(b for b in blocks if b["type"] == "actions")
        assert [e["action_id"] for e in actions["elements"]] == ["ack_incident", "resolve_incident"]

        # same alert again -> no second incident, no second post, counter bumped on the message
        c.post("/alerts", json=PAYLOAD)
        assert _wait(lambda: slack.chat_update.await_count == 1)
        assert slack.chat_postMessage.await_count == 1
        assert len(c.get("/incidents").json()) == 1
        assert c.get("/incidents").json()[0]["alert_count"] == 2

        # ack -> message updated with only a Resolve button
        r = c.post(f"/incidents/{inc['id']}/ack?user=alice")
        assert r.json()["status"] == "acknowledged"
        upd = slack.chat_update.await_args.kwargs
        assert upd["channel"] == "C123" and upd["ts"] == "1700000000.000100"
        actions = next(b for b in upd["blocks"] if b["type"] == "actions")
        assert [e["action_id"] for e in actions["elements"]] == ["resolve_incident"]
        assert c.post(f"/incidents/{inc['id']}/ack").status_code == 409  # double click

        # resolve -> buttons gone; after resolve, a new alert opens a NEW incident
        assert c.post(f"/incidents/{inc['id']}/resolve").json()["status"] == "resolved"
        assert not any(
            b["type"] == "actions" for b in slack.chat_update.await_args.kwargs["blocks"]
        )
        c.post("/alerts", json=PAYLOAD)
        assert _wait(lambda: slack.chat_postMessage.await_count == 2)
        assert len(c.get("/incidents").json()) == 2

    done = store.get(inc["id"])
    assert done.acknowledged_at and done.resolved_at and done.acked_by == "alice"
    assert done.acknowledged_at <= done.resolved_at


def test_bad_payload_rejected(env):
    _, _, svc = env
    with TestClient(create_app(Deps(svc, Commands(svc), dry_run=True))) as c:
        assert c.post("/alerts", json={"nope": 1}).status_code == 422


def test_resolved_alerts_are_ignored(env):
    slack, _, svc = env
    payload = {"alerts": [{**PAYLOAD["alerts"][0], "status": "resolved"}]}
    import asyncio

    assert asyncio.run(svc.handle_alerts(payload)) == []
    slack.chat_postMessage.assert_not_awaited()


async def test_slash_commands(env, monkeypatch):
    slack, store, svc = env
    cmds = Commands(svc)
    _, blocks = await cmds.incident("list")
    assert "No open incidents" in _texts(blocks)

    ids = await svc.handle_alerts(PAYLOAD)
    _, blocks = await cmds.incident("list")
    assert f"#{ids[0]}" in _texts(blocks) and "HighErrorRate" in _texts(blocks)

    _, blocks = await cmds.incident(f"summary {ids[0]}")
    assert "0.41" in _texts(blocks)
    assert "No incident #99" in _texts((await cmds.incident("summary 99"))[1])
    assert "Usage" in (await cmds.incident("bogus"))[0]

    _, blocks = await cmds.ask("why is checkout slow?")
    assert "0.41" in _texts(blocks)

    async def fake_status(url):
        return [{"service": "checkout", "up": True, "error_ratio": "0.41", "p95": "0.03"}]

    monkeypatch.setattr(incidents_mod, "get_status", fake_status)
    _, blocks = await cmds.status()
    assert "checkout" in _texts(blocks) and "0.41" in _texts(blocks)

    async def down(url):
        raise ConnectionError("prometheus down")

    monkeypatch.setattr(incidents_mod, "get_status", down)
    assert "Could not reach Prometheus" in _texts((await cmds.status())[1])


def test_metrics_endpoint_reports_incident_stats(env):
    from datetime import timedelta

    from app.metrics import bind_store

    _, store, svc = env
    bind_store(store)
    a, _ = store.open_or_dedupe("f1", "HighLatency", "checkout", "warning")
    b, _ = store.open_or_dedupe("f2", "HighErrorRate", "checkout", "critical")
    store.ack(a.id, "bob")
    store.resolve(a.id, "bob")
    with store.session() as s:  # make the timings deterministic: ack after 30s, resolve after 90s
        row = s.get(type(a), a.id)
        row.acknowledged_at = row.created_at + timedelta(seconds=30)
        row.resolved_at = row.created_at + timedelta(seconds=90)
        s.commit()
    with TestClient(create_app(Deps(svc, Commands(svc), dry_run=True))) as c:
        text = c.get("/metrics").text
    assert 'opspilot_open_incidents{severity="critical"} 1.0' in text
    assert "opspilot_mtta_seconds 30.0" in text
    assert "opspilot_mttr_seconds 90.0" in text
    assert "opspilot_incidents_total 2.0" in text
    assert "opspilot_llm_latency_seconds" in text or "opspilot_alerts_received_total" in text
    assert b.id
