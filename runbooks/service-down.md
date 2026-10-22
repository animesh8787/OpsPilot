# Service Down

**Alert:** ServiceDown - Prometheus cannot scrape the service.
**Keywords:** down unreachable crash scrape up outage restart

## Triage
1. Is the process running? Check container status and restart count.
2. Read the last log lines before the outage for crashes or OOM kills.
3. Check network and DNS between Prometheus and the target.

## Mitigation
- Restart the service.
- Roll back if the crash began after a deploy.
