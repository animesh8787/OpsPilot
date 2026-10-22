"""Incident lifecycle: alert webhook -> triage -> Slack, plus ack/resolve and slash commands."""

import logging

from app.agent import Agent
from app.db import Incident, Store
from app.metrics import ALERTS, INCIDENTS
from app.notifier import SlackNotifier
from app.slack_blocks import (
    incident_blocks,
    incident_text,
    list_blocks,
    status_blocks,
    text_blocks,
)
from app.status import get_status

log = logging.getLogger("opspilot.incidents")


class IncidentService:
    def __init__(self, store: Store, agent: Agent, notifier: SlackNotifier, prometheus_url: str):
        self.store, self.agent, self.notifier = store, agent, notifier
        self.prometheus_url = prometheus_url

    async def handle_alerts(self, payload: dict) -> list[int]:
        """Process an Alertmanager webhook. Returns ids of incidents touched."""
        ids = []
        for alert in payload.get("alerts", []):
            if alert.get("status", "firing") != "firing":
                continue
            labels = alert.get("labels", {})
            alertname, service = (
                labels.get("alertname", "unknown"),
                labels.get("service", "unknown"),
            )
            ALERTS.labels(service, alertname).inc()
            inc, created = self.store.open_or_dedupe(
                alert.get("fingerprint", ""), alertname, service, labels.get("severity", "warning")
            )
            ids.append(inc.id)
            if not created:
                log.info("deduplicated alert", extra={"extra_fields": {"incident": inc.id}})
                await self._refresh(inc.id)  # only bumps the alert counter on the existing message
                continue
            INCIDENTS.labels(service, inc.severity).inc()
            try:
                self.store.save_triage(inc.id, await self.agent.triage(alert))
                inc = self.store.get(inc.id)
                channel, ts = await self.notifier.post(incident_text(inc), incident_blocks(inc))
                self.store.set_slack(inc.id, channel, ts)
                log.info("incident posted", extra={"extra_fields": {"incident": inc.id}})
            except Exception:
                log.exception("failed to post incident %s", inc.id)
        return ids

    async def _refresh(self, incident_id: int) -> Incident | None:
        inc = self.store.get(incident_id)
        if inc and inc.slack_ts:
            try:
                await self.notifier.update(
                    inc.slack_channel, inc.slack_ts, incident_text(inc), incident_blocks(inc)
                )
            except Exception:
                log.exception("failed to update slack message for incident %s", incident_id)
        return inc

    async def ack(self, incident_id: int, user: str) -> Incident | None:
        if self.store.ack(incident_id, user):
            return await self._refresh(incident_id)
        return None

    async def resolve(self, incident_id: int, user: str) -> Incident | None:
        if self.store.resolve(incident_id, user):
            return await self._refresh(incident_id)
        return None


class Commands:
    """Slash-command logic; returns (fallback text, blocks) so it is testable without Slack."""

    def __init__(self, service: IncidentService) -> None:
        self.svc = service

    async def status(self) -> tuple[str, list[dict]]:
        try:
            return "Service status", status_blocks(await get_status(self.svc.prometheus_url))
        except Exception as e:  # noqa: BLE001
            return "Status unavailable", text_blocks(f"Could not reach Prometheus: {e}")

    async def incident(self, text: str) -> tuple[str, list[dict]]:
        parts = text.split()
        if parts[:1] == ["list"] or not parts:
            return "Open incidents", list_blocks(self.svc.store.list_open())
        if parts[0] == "summary" and len(parts) == 2 and parts[1].isdigit():
            inc = self.svc.store.get(int(parts[1]))
            if not inc:
                return "Not found", text_blocks(f"No incident #{parts[1]}.")
            t = inc.triage
            desc = (
                f"incident #{inc.id} {inc.alertname} on {inc.service}, status {inc.status}, "
                f"opened {inc.created_at:%Y-%m-%d %H:%M} UTC, {inc.alert_count} alert(s). "
                f"Triage: {t.summary if t else 'n/a'} Cause: {t.likely_cause if t else 'n/a'}"
            )
            return f"Incident #{inc.id} summary", text_blocks(await self.svc.agent.summarize(desc))
        return "Usage", text_blocks("Usage: /incident list | /incident summary <id>")

    async def ask(self, question: str) -> tuple[str, list[dict]]:
        if not question.strip():
            return "Usage", text_blocks("Usage: /ask <question>, e.g. /ask why is checkout slow?")
        return "Answer", text_blocks(await self.svc.agent.ask(question))
