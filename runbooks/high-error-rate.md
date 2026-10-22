# High Error Rate

**Alert:** HighErrorRate - more than 5% of requests return 5xx.
**Keywords:** errors 5xx failures exceptions error rate

## Triage
1. Check recent deploys; roll back if the error spike started right after one.
2. Search logs for the dominant ERROR message (DB pool exhausted, upstream timeouts, gateway 502).
3. Check dependency health (database, payment gateway, inventory service).

## Mitigation
- Roll back the last deploy.
- Disable the failing feature flag.
- If a dependency is down, enable the circuit breaker and degrade gracefully.

## Escalation
Page the service owner if errors persist for more than 15 minutes.
