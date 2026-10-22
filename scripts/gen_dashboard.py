"""Generates deploy/grafana/dashboards/opspilot.json (keeps the JSON reviewable as code)."""

import json
from pathlib import Path

DS = {"type": "prometheus", "uid": "prometheus"}
_id = 0


def _panel(kind, title, targets, x, y, w=8, h=7, unit=None, **extra):
    global _id
    _id += 1
    p = {
        "id": _id,
        "type": kind,
        "title": title,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [
            {"datasource": DS, "refId": chr(65 + i), "expr": e, "legendFormat": legend}
            for i, (e, legend) in enumerate(targets)
        ],
        "fieldConfig": {"defaults": {"unit": unit or "short"}, "overrides": []},
    }
    p.update(extra)
    return p


def stat(title, expr, x, unit=None, w=4):
    return _panel(
        "stat",
        title,
        [(expr, "")],
        x,
        0,
        w=w,
        h=4,
        unit=unit,
        options={"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value"},
    )


ERR = 'sum(rate(http_requests_total{status=~"5.."}[1m])) / sum(rate(http_requests_total[1m]))'
P95 = "histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[1m])))"

panels = [
    stat("Open incidents", "sum(opspilot_open_incidents) or vector(0)", 0),
    stat("MTTA", "opspilot_mtta_seconds", 4, "s"),
    stat("MTTR", "opspilot_mttr_seconds", 8, "s"),
    stat("Total incidents", "opspilot_incidents_total", 12),
    stat("Checkout 5xx ratio", ERR, 16, "percentunit"),
    stat("Checkout p95 latency", P95, 20, "s"),
    _panel(
        "timeseries",
        "Incident volume (created per 5m)",
        [
            (
                "sum by (service, severity) (increase(opspilot_incidents_created_total[5m]))",
                "{{service}} {{severity}}",
            )
        ],
        0,
        4,
        drawStyle="bars",
    ),
    _panel(
        "timeseries",
        "MTTA and MTTR",
        [("opspilot_mtta_seconds", "MTTA"), ("opspilot_mttr_seconds", "MTTR")],
        8,
        4,
        unit="s",
    ),
    _panel(
        "bargauge",
        "Alert noise per service (last 1h): alerts received vs incidents opened",
        [
            ("sum by (service) (increase(opspilot_alerts_received_total[1h]))", "alerts"),
            ("sum by (service) (increase(opspilot_incidents_created_total[1h]))", "incidents"),
        ],
        16,
        4,
    ),
    _panel("timeseries", "Checkout 5xx ratio", [(ERR, "5xx ratio")], 0, 11, unit="percentunit"),
    _panel(
        "timeseries",
        "Checkout latency (p50 / p95)",
        [
            (
                "histogram_quantile(0.5, sum by (le) (rate(http_request_duration_seconds_bucket[1m])))",
                "p50",
            ),
            (P95, "p95"),
        ],
        8,
        11,
        unit="s",
    ),
    _panel(
        "timeseries",
        "Checkout request rate",
        [("sum by (status) (rate(http_requests_total[1m]))", "{{status}}")],
        16,
        11,
        unit="reqps",
    ),
    _panel(
        "timeseries",
        "OpsPilot LLM latency p95",
        [
            (
                "histogram_quantile(0.95, sum by (le, provider) (rate(opspilot_llm_latency_seconds_bucket[5m])))",
                "{{provider}}",
            )
        ],
        0,
        18,
        unit="s",
    ),
    _panel(
        "timeseries",
        "OpsPilot LLM tokens (per 5m)",
        [("sum by (direction) (increase(opspilot_llm_tokens_total[5m]))", "{{direction}}")],
        8,
        18,
    ),
    _panel(
        "timeseries",
        "MCP tool calls (per 5m)",
        [
            (
                "sum by (tool, status) (increase(opspilot_tool_calls_total[5m]))",
                "{{tool}} {{status}}",
            )
        ],
        16,
        18,
    ),
]

dashboard = {
    "uid": "opspilot",
    "title": "OpsPilot",
    "tags": ["opspilot"],
    "timezone": "browser",
    "schemaVersion": 39,
    "version": 1,
    "refresh": "10s",
    "time": {"from": "now-30m", "to": "now"},
    "panels": panels,
}

out = Path(__file__).parent.parent / "deploy/grafana/dashboards/opspilot.json"
out.write_text(json.dumps(dashboard, indent=2) + "\n")
print(f"wrote {out} ({len(panels)} panels)")
