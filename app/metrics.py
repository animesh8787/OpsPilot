"""Prometheus metrics exposed by OpsPilot at /metrics."""

from prometheus_client import Counter, Histogram

ALERTS = Counter("opspilot_alerts_received_total", "Alerts received", ["service", "alertname"])
INCIDENTS = Counter(
    "opspilot_incidents_created_total", "Incidents created", ["service", "severity"]
)
LLM_LATENCY = Histogram(
    "opspilot_llm_latency_seconds",
    "LLM call latency",
    ["provider"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60),
)
LLM_TOKENS = Counter("opspilot_llm_tokens_total", "LLM tokens", ["provider", "direction"])
TOOL_CALLS = Counter("opspilot_tool_calls_total", "MCP tool calls", ["tool", "status"])
