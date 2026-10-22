"""Block Kit builders (pure functions)."""

from app.db import Incident

SEVERITY_ICON = {
    "critical": ":red_circle:",
    "warning": ":large_orange_circle:",
    "info": ":large_blue_circle:",
}


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _md(text: str) -> dict:
    return {"type": "mrkdwn", "text": text}


def incident_text(inc: Incident) -> str:
    return f"[{inc.severity.upper()}] {inc.alertname} on {inc.service} (incident #{inc.id})"


def incident_blocks(inc: Incident) -> list[dict]:
    t = inc.triage
    icon = SEVERITY_ICON.get(inc.severity, ":white_circle:")
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"#{inc.id} {inc.alertname} on {inc.service}"},
        },
        {"type": "section", "text": _md(f"{icon} *{inc.severity.upper()}*  |  *{inc.status}*")},
    ]
    if t:
        blocks.append({"type": "section", "text": _md(f"*Summary*\n{esc(t.summary)}")})
        if t.likely_cause:
            blocks.append(
                {"type": "section", "text": _md(f"*Likely cause*\n{esc(t.likely_cause)}")}
            )
        if t.evidence:
            bullets = "\n".join(f"• {esc(e)}" for e in t.evidence)
            blocks.append({"type": "section", "text": _md(f"*Evidence*\n{bullets}")})
        if t.runbook_url:
            blocks.append(
                {
                    "type": "section",
                    "text": _md(
                        f"*Runbook*\n<{t.runbook_url}|{esc(t.runbook_title or 'Runbook')}>"
                    ),
                }
            )
    ctx = [f"opened {inc.created_at:%H:%M:%S} UTC", f"alerts received: {inc.alert_count}"]
    if inc.acknowledged_at:
        ctx.append(f"acknowledged by {esc(inc.acked_by)} at {inc.acknowledged_at:%H:%M:%S} UTC")
    if inc.resolved_at:
        ctx.append(f"resolved by {esc(inc.resolved_by)} at {inc.resolved_at:%H:%M:%S} UTC")
    blocks.append({"type": "context", "elements": [_md(" | ".join(ctx))]})
    if inc.status != "resolved":
        buttons = []
        if inc.status == "open":
            buttons.append(_button("Acknowledge", "ack_incident", inc.id, None))
        buttons.append(_button("Resolve", "resolve_incident", inc.id, "primary"))
        blocks.append({"type": "actions", "elements": buttons})
    return blocks


def _button(label: str, action_id: str, incident_id: int, style: str | None) -> dict:
    b = {
        "type": "button",
        "text": {"type": "plain_text", "text": label},
        "action_id": action_id,
        "value": str(incident_id),
    }
    if style:
        b["style"] = style
    return b


def list_blocks(incidents: list[Incident]) -> list[dict]:
    if not incidents:
        return [{"type": "section", "text": _md(":white_check_mark: No open incidents.")}]
    lines = [
        f"*#{i.id}* {SEVERITY_ICON.get(i.severity, '')} {esc(i.alertname)} on {esc(i.service)} "
        f"- {i.status}, opened {i.created_at:%H:%M} UTC, {i.alert_count} alert(s)"
        for i in incidents
    ]
    return [{"type": "section", "text": _md("*Open incidents*\n" + "\n".join(lines))}]


def status_blocks(rows: list[dict]) -> list[dict]:
    if not rows:
        return [{"type": "section", "text": _md("No services found in Prometheus.")}]
    lines = []
    for r in rows:
        icon = ":large_green_circle:" if r["up"] else ":red_circle:"
        extra = ""
        if r.get("error_ratio") is not None:
            extra += f", 5xx ratio {r['error_ratio']}"
        if r.get("p95") is not None:
            extra += f", p95 {r['p95']}s"
        lines.append(f"{icon} *{esc(r['service'])}* {'up' if r['up'] else 'DOWN'}{extra}")
    return [{"type": "section", "text": _md("*Service status*\n" + "\n".join(lines))}]


def text_blocks(text: str) -> list[dict]:
    return [{"type": "section", "text": _md(esc(text)[:2900])}]
