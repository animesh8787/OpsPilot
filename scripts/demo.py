"""make demo: turn on chaos, wait for OpsPilot to open an incident, print where to look.

Usage: python scripts/demo.py [--reset]   (stdlib only; stack must be running: make up)
"""

import json
import sys
import time
import urllib.request

DEMO = "http://localhost:8001"
OPSPILOT = "http://localhost:8000"
TIMEOUT_S = 180


def call(url: str, body: dict | None = None):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def main() -> int:
    if "--reset" in sys.argv:
        print("chaos off:", call(f"{DEMO}/chaos", {"error_rate": 0, "latency_ms": 0}))
        return 0
    try:
        known = {i["id"] for i in call(f"{OPSPILOT}/incidents")}
    except OSError as e:
        print(f"OpsPilot is not reachable at {OPSPILOT} ({e}). Run `make up` first.")
        return 1
    print("chaos on:", call(f"{DEMO}/chaos", {"error_rate": 0.4, "latency_ms": 700}))
    start = time.time()
    print(
        "waiting for Prometheus to fire an alert (rule `for: 30s` + Alertmanager group_wait 10s)..."
    )
    while time.time() - start < TIMEOUT_S:
        new = [i for i in call(f"{OPSPILOT}/incidents") if i["id"] not in known]
        if new:
            break
        time.sleep(3)
    else:
        print(f"no incident after {TIMEOUT_S}s: check `docker compose logs opspilot alertmanager`")
        return 1
    print(f"\nincident opened {time.time() - start:.0f}s after enabling chaos:\n")
    for i in new:
        print(f"  #{i['id']} [{i['severity']}] {i['alertname']} on {i['service']}")
        print(f"     summary: {i['summary']}")
        print(f"     cause:   {i['likely_cause']}")
        for e in i["evidence"]:
            print(f"     - {e}")
        print(f"     runbook: {i['runbook_url']}")
    first = new[0]["id"]
    print(f"""
What to look at:
  Slack    #incidents: the incident message with Acknowledge / Resolve buttons
           (dry-run mode, no Slack tokens: `docker compose logs opspilot | grep "DRY-RUN slack post"`)
  Grafana  http://localhost:3000/d/opspilot  (error rate and latency spike, incident volume)
  Alerts   http://localhost:9093 (Alertmanager)   http://localhost:9090/alerts (Prometheus)
Try:
  Slack    /opsstatus, /incident list, /incident summary {first}, /ask why is checkout slow?
  No Slack curl -X POST "localhost:8000/incidents/{first}/ack?user=me"    (then .../resolve)
           watch MTTA / MTTR update on the dashboard
Clean up: python scripts/demo.py --reset""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
