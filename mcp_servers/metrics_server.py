"""MCP server: PromQL queries against Prometheus."""

import time

import httpx
from mcp.server.fastmcp import FastMCP

from app.config import get_settings

mcp = FastMCP("metrics")


def _get(path: str, params: dict) -> dict:
    r = httpx.get(f"{get_settings().prometheus_url}{path}", params=params, timeout=10)
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "success":
        raise ValueError(body.get("error", "prometheus query failed"))
    return body["data"]


def _labels(metric: dict) -> str:
    return ",".join(f"{k}={v}" for k, v in metric.items() if k != "__name__") or "{}"


@mcp.tool()
def prom_query(query: str) -> str:
    """Run an instant PromQL query. Returns one line per series: labels => value."""
    try:
        data = _get("/api/v1/query", {"query": query})
    except (httpx.HTTPError, ValueError) as e:
        return f"ERROR: {e}"
    rows = [f"{_labels(s['metric'])} => {s['value'][1]}" for s in data["result"]]
    return "\n".join(rows) or "no data"


@mcp.tool()
def prom_query_range(query: str, minutes: int = 15, step_s: int = 15) -> str:
    """Run a PromQL range query over the last N minutes. Returns min/avg/max/last per series."""
    end = time.time()
    try:
        data = _get(
            "/api/v1/query_range",
            {"query": query, "start": end - minutes * 60, "end": end, "step": step_s},
        )
    except (httpx.HTTPError, ValueError) as e:
        return f"ERROR: {e}"
    rows = []
    for s in data["result"]:
        vals = [float(v) for _, v in s["values"] if v != "NaN"]
        if vals:
            rows.append(
                f"{_labels(s['metric'])} => min={min(vals):.4g} avg={sum(vals) / len(vals):.4g} "
                f"max={max(vals):.4g} last={vals[-1]:.4g} (n={len(vals)}, window={minutes}m)"
            )
    return "\n".join(rows) or "no data"


if __name__ == "__main__":
    mcp.run()
