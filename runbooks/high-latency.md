# High Latency

**Alert:** HighLatency - p95 request latency above 500ms.
**Keywords:** latency slow p95 timeout response time slowness

## Triage
1. Compare p50 vs p95: a wide gap points to a slow dependency or queueing.
2. Search logs for slow or timed out warnings.
3. Check CPU, memory and connection-pool saturation.

## Mitigation
- Scale out replicas if CPU-bound.
- Restart pods with stuck connections.
- Rate limit while investigating downstream dependencies.
