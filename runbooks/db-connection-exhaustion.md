# Database Connection Pool Exhaustion

**Alert:** errors mentioning connection pool exhausted or database timeouts.
**Keywords:** database db connection pool exhausted timeout postgres connections

## Triage
1. Compare active connections vs pool size and DB max_connections.
2. Look for long-running queries or transactions holding connections.
3. Check for connection leaks after recent deploys.

## Mitigation
- Kill long-running queries.
- Temporarily increase the pool size.
- Restart the app to release leaked connections.
