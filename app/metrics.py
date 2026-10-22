"""Prometheus metrics exposed by OpsPilot at /metrics."""

from prometheus_client import REGISTRY, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

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


class StoreCollector(Collector):
    """Computes incident gauges from SQLite at scrape time, so they survive restarts."""

    store = None  # set by bind_store()

    def collect(self):
        if self.store is None:
            return
        st = self.store.stats()
        g = GaugeMetricFamily(
            "opspilot_open_incidents", "Unresolved incidents", labels=["severity"]
        )
        for sev, n in st["open_by_severity"].items():
            g.add_metric([sev], n)
        yield g
        yield GaugeMetricFamily(
            "opspilot_mtta_seconds", "Mean time to acknowledge", value=st["mtta"]
        )
        yield GaugeMetricFamily("opspilot_mttr_seconds", "Mean time to resolve", value=st["mttr"])
        yield GaugeMetricFamily("opspilot_incidents_total", "All incidents", value=st["total"])


_collector = StoreCollector()
REGISTRY.register(_collector)


def bind_store(store) -> None:
    _collector.store = store
