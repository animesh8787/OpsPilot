import json
import os
import sys
import time
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.config import get_settings
from mcp_servers import logs_server, metrics_server, runbooks_server

RUNBOOKS = Path(__file__).parent.parent / "runbooks"


def _line(level: str, msg: str, age_s: int = 0) -> str:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - age_s))
    return json.dumps({"ts": ts, "level": level, "msg": msg})


@pytest.fixture
def logfile(tmp_path):
    p = tmp_path / "app.log"
    p.write_text(
        "\n".join(
            [
                _line("ERROR", "db connection pool exhausted order 1", 10),
                _line("ERROR", "db connection pool exhausted order 2", 5),
                _line("INFO", "checkout ok", 5),
                _line("ERROR", "ancient failure", 7200),
                "not json",
            ]
        )
    )
    return p


def test_logs_filters_by_level_window_keyword(logfile):
    r = logs_server.search(logfile, minutes=10, level="error")
    assert r["matched"] == 2  # the 2h-old line is outside the window
    assert r["top_messages"][0] == {"msg": "db connection pool exhausted order #", "count": 2}
    assert logs_server.search(logfile, keyword="checkout")["matched"] == 1
    assert logs_server.search(logfile, minutes=300, level="ERROR")["matched"] == 3


def test_logs_missing_file(tmp_path):
    assert logs_server.search(tmp_path / "nope.log")["matched"] == 0


def test_runbooks_best_match():
    m = runbooks_server.best_matches(RUNBOOKS, "http://x", "HighLatency p95 slow")
    assert m[0]["name"] == "high-latency"
    assert m[0]["url"] == "http://x/high-latency.md"
    db = runbooks_server.best_matches(RUNBOOKS, "http://x", "connection pool exhausted")
    assert db[0]["name"] == "db-connection-exhaustion"
    assert runbooks_server.best_matches(RUNBOOKS, "http://x", "zzzz") == []


def test_runbook_get_rejects_traversal(monkeypatch):
    monkeypatch.setenv("RUNBOOKS_DIR", str(RUNBOOKS))
    get_settings.cache_clear()
    assert runbooks_server.get_runbook("../pyproject").startswith("ERROR")
    assert "High Latency" in runbooks_server.get_runbook("high-latency")
    get_settings.cache_clear()


def test_metrics_formats_and_errors(monkeypatch):
    class R:
        def raise_for_status(self): ...

        def json(self):
            return {
                "status": "success",
                "data": {"result": [{"metric": {"service": "checkout"}, "value": [0, "0.42"]}]},
            }

    monkeypatch.setattr(metrics_server.httpx, "get", lambda *a, **k: R())
    assert metrics_server.prom_query("x") == "service=checkout => 0.42"

    def boom(*a, **k):
        raise metrics_server.httpx.ConnectError("down")

    monkeypatch.setattr(metrics_server.httpx, "get", boom)
    assert metrics_server.prom_query("x").startswith("ERROR")


@pytest.mark.parametrize(
    "module,tools",
    [
        ("mcp_servers.metrics_server", {"prom_query", "prom_query_range"}),
        ("mcp_servers.logs_server", {"search_logs"}),
        ("mcp_servers.runbooks_server", {"search_runbooks", "get_runbook"}),
    ],
)
async def test_server_over_stdio(module, tools):
    env = {**os.environ, "RUNBOOKS_DIR": str(RUNBOOKS)}
    params = StdioServerParameters(command=sys.executable, args=["-m", module], env=env)
    async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
        await session.initialize()
        assert {t.name for t in (await session.list_tools()).tools} == tools
        if module.endswith("runbooks_server"):
            res = await session.call_tool("search_runbooks", {"query": "disk full"})
            assert "disk-full" in res.content[0].text
