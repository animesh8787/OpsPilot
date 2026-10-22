"""Service health straight from Prometheus (used by /opsstatus)."""

import httpx


async def _instant(client: httpx.AsyncClient, query: str) -> dict[str, str]:
    r = await client.get("/api/v1/query", params={"query": query})
    r.raise_for_status()
    return {s["metric"].get("service", "?"): s["value"][1] for s in r.json()["data"]["result"]}


async def get_status(prometheus_url: str) -> list[dict]:
    async with httpx.AsyncClient(base_url=prometheus_url, timeout=10) as c:
        up = await _instant(c, "up")
        err = await _instant(
            c,
            'round(sum by (service) (rate(http_requests_total{status=~"5.."}[1m]))'
            " / sum by (service) (rate(http_requests_total[1m])), 0.001)",
        )
        p95 = await _instant(
            c,
            "round(histogram_quantile(0.95, sum by (le, service) "
            "(rate(http_request_duration_seconds_bucket[1m]))), 0.001)",
        )
    return [
        {
            "service": svc,
            "up": v == "1",
            "error_ratio": err.get(svc),
            "p95": p95.get(svc),
        }
        for svc, v in sorted(up.items())
    ]
