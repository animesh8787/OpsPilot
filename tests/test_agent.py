import asyncio
import json

import httpx
import pytest

from app.agent import Agent, parse_triage
from app.config import Settings
from app.llm.anthropic_provider import to_anthropic_messages
from app.llm.base import LLMReply, ToolCall
from app.llm.factory import make_provider
from app.llm.mock_provider import MockProvider
from app.llm.ollama_provider import OllamaProvider

ALERT = {
    "labels": {"alertname": "HighErrorRate", "service": "checkout", "severity": "critical"},
    "annotations": {"summary": "checkout 5xx ratio above 5%"},
    "startsAt": "2026-10-22T10:00:00Z",
}
LOGS = json.dumps(
    {
        "matched": 12,
        "top_messages": [{"msg": "db connection pool exhausted: timeout after #s", "count": 9}],
        "latest": [{"msg": "db connection pool exhausted: timeout after 5s"}],
    }
)
RUNBOOK = json.dumps(
    [{"name": "high-error-rate", "title": "High Error Rate", "url": "http://x/high-error-rate.md"}]
)


class FakeHub:
    def __init__(self):
        self.calls = []

    def tools(self):
        return [{"name": "prom_query", "description": "", "input_schema": {}}]

    async def call(self, name, args):
        self.calls.append(name)
        if name == "prom_query":
            return "service=checkout => 0.41" if "5.." in args["query"] else "{} => 0.03"
        return {"search_logs": LOGS, "search_runbooks": RUNBOOK}.get(name, "ERROR: unknown")


async def test_triage_with_mock_cites_tool_output():
    hub = FakeHub()
    t = await Agent(MockProvider(), hub).triage(ALERT)
    assert "0.41" in " ".join(t.evidence)
    assert "db connection pool exhausted" in t.likely_cause
    assert t.runbook_url == "http://x/high-error-rate.md"
    assert t.severity == "critical"
    assert not any("unverified" in e for e in t.evidence)
    assert {"prom_query", "search_logs", "search_runbooks"} <= set(hub.calls)


async def test_ask_with_mock():
    out = await Agent(MockProvider(), FakeHub()).ask("why is checkout slow?")
    assert "0.41" in out and "High Error Rate" in out


def test_invented_numbers_are_flagged():
    text = json.dumps({"summary": "s", "evidence": ["5xx = 0.41", "p99 = 987ms"]})
    t = parse_triage(text, "ratio => 0.41", "warning")
    assert t.evidence[0] == "5xx = 0.41"
    assert "unverified" in t.evidence[1]


class LoopingLLM:
    """Always asks for another tool call; the agent must stop it."""

    name = "loop"

    def __init__(self):
        self.tool_offers = []

    async def chat(self, system, messages, tools):
        self.tool_offers.append(len(tools))
        if tools:
            return LLMReply(
                tool_calls=[ToolCall(f"c{len(messages)}", "prom_query", {"query": "up"})]
            )
        return LLMReply(text="final answer")


async def test_tool_call_budget_is_enforced():
    hub, llm = FakeHub(), LoopingLLM()
    out = await Agent(llm, hub, max_tool_calls=3).ask("q")
    assert len(hub.calls) == 3
    assert out == "final answer"
    assert llm.tool_offers[-1] == 0  # tools withdrawn once budget is spent


class SlowLLM:
    name = "slow"

    async def chat(self, system, messages, tools):
        await asyncio.sleep(5)


async def test_timeout_still_yields_incident_triage():
    t = await Agent(SlowLLM(), FakeHub(), timeout_s=0.1).triage(ALERT)
    assert "triage failed" in t.summary and t.severity == "critical"
    assert "couldn't answer" in await Agent(SlowLLM(), FakeHub(), timeout_s=0.1).ask("q")


async def test_ollama_tool_call_roundtrip():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "prom_query", "arguments": {"query": "up"}}}
                    ],
                },
                "prompt_eval_count": 11,
                "eval_count": 7,
            },
        )

    p = OllamaProvider("http://ollama", transport=httpx.MockTransport(handler))
    tools = [{"name": "prom_query", "description": "d", "input_schema": {"type": "object"}}]
    r = await p.chat("sys", [{"role": "user", "content": "hi"}], tools)
    assert r.tool_calls[0].name == "prom_query" and r.tool_calls[0].args == {"query": "up"}
    assert (r.usage.input_tokens, r.usage.output_tokens) == (11, 7)
    assert seen["body"]["tools"][0]["function"]["parameters"] == {"type": "object"}
    assert seen["body"]["messages"][0] == {"role": "system", "content": "sys"}


def test_anthropic_message_conversion():
    msgs = [
        {"role": "user", "content": "q"},
        {
            "role": "assistant",
            "text": "ok",
            "tool_calls": [ToolCall("t1", "x", {"a": 1})],
            "raw": None,
        },
        {
            "role": "tool",
            "results": [{"id": "t1", "name": "x", "content": "out", "is_error": False}],
        },
    ]
    out = to_anthropic_messages(msgs)
    assert out[1]["content"][1] == {"type": "tool_use", "id": "t1", "name": "x", "input": {"a": 1}}
    assert out[2]["content"][0]["tool_use_id"] == "t1"
    msgs[1]["raw"] = ["RAW"]
    assert to_anthropic_messages(msgs)[1]["content"] == ["RAW"]


def test_factory():
    assert make_provider(Settings(_env_file=None, llm_provider="mock")).name == "mock"
    assert make_provider(Settings(_env_file=None, llm_provider="ollama")).name == "ollama"
    with pytest.raises(ValueError):
        make_provider(Settings(_env_file=None, llm_provider="nope"))
