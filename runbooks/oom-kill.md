# Out Of Memory (OOM)

**Alert:** container restarts with OOMKilled, exit code 137.
**Keywords:** oom memory out of memory killed 137 leak heap

## Triage
1. Check the memory usage trend; a steady climb suggests a leak.
2. Look for large payloads or unbounded caches in recent changes.

## Mitigation
- Raise the memory limit temporarily.
- Restart the service and roll back the leaking change.
