"""Tool-calling agent: gathers evidence through MCP tools, then answers."""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Protocol

from app.llm.base import LLMProvider
from app.metrics import LLM_LATENCY, LLM_TOKENS

log = logging.getLogger("opspilot.agent")

SYSTEM_PROMPT = """You are OpsPilot, an SRE incident-triage assistant.
Rules:
- Be concise and evidence-based. No filler, no speculation presented as fact.
- Use the tools to gather evidence BEFORE answering: metrics (Prometheus), logs, runbooks.
- Every number, timestamp or log line you state MUST be copied from tool output. Never invent
  or estimate values. If the tools returned nothing useful, say "no evidence found".
- If a tool returns an ERROR, say so and work with what you have.
- Services are labelled by `service`; the demo service is `checkout`. Useful metrics:
  http_requests_total{status}, http_request_duration_seconds_bucket, up{job}.
"""

TRIAGE_SUFFIX = """
Task: triage the alert. After using tools, reply with ONLY a JSON object:
{"summary": "<1-2 sentences>", "likely_cause": "<one sentence, grounded in evidence>",
 "evidence": ["<short fact with the real number or log line>", ...],
 "runbook_title": "<from search_runbooks, or empty>",
 "runbook_url": "<from search_runbooks, or empty>",
 "severity": "critical|warning|info"}
"""


class ToolRunner(Protocol):
    def tools(self) -> list[dict]: ...
    async def call(self, name: str, args: dict) -> str: ...


@dataclass
class Triage:
    summary: str
    likely_cause: str = ""
    evidence: list[str] = field(default_factory=list)
    runbook_title: str = ""
    runbook_url: str = ""
    severity: str = "warning"


class Agent:
    def __init__(
        self, llm: LLMProvider, hub: ToolRunner, max_tool_calls: int = 8, timeout_s: float = 60
    ) -> None:
        self.llm, self.hub = llm, hub
        self.max_tool_calls, self.timeout_s = max_tool_calls, timeout_s

    async def _run(self, system: str, prompt: str) -> tuple[str, str]:
        """Returns (final text, concatenated tool output used for fact-checking)."""
        messages: list[dict] = [{"role": "user", "content": prompt}]
        calls, seen = 0, []
        for _ in range(self.max_tool_calls + 3):
            tools = self.hub.tools() if calls < self.max_tool_calls else []
            t0 = time.perf_counter()
            reply = await self.llm.chat(system, messages, tools)
            LLM_LATENCY.labels(self.llm.name).observe(time.perf_counter() - t0)
            LLM_TOKENS.labels(self.llm.name, "input").inc(reply.usage.input_tokens)
            LLM_TOKENS.labels(self.llm.name, "output").inc(reply.usage.output_tokens)
            if not reply.tool_calls or not tools:
                return reply.text, "\n".join(seen)
            messages.append(
                {
                    "role": "assistant",
                    "text": reply.text,
                    "tool_calls": reply.tool_calls,
                    "raw": reply.raw,
                }
            )
            results = []
            for tc in reply.tool_calls:
                if calls >= self.max_tool_calls:
                    out = "ERROR: tool call budget exhausted, answer with the evidence you have"
                else:
                    calls += 1
                    out = await self.hub.call(tc.name, tc.args)
                    seen.append(
                        json.dumps(tc.args)
                    )  # numbers the agent itself asked for are fair game
                    log.info(
                        "tool call", extra={"extra_fields": {"tool": tc.name, "args": tc.args}}
                    )
                seen.append(out)
                results.append(
                    {
                        "id": tc.id,
                        "name": tc.name,
                        "content": out,
                        "is_error": out.startswith("ERROR"),
                    }
                )
            messages.append({"role": "tool", "results": results})
        raise RuntimeError("agent did not converge")

    async def ask(self, question: str) -> str:
        try:
            text, seen = await asyncio.wait_for(
                self._run(SYSTEM_PROMPT, f"QUESTION: {question}"), self.timeout_s
            )
        except Exception as e:  # noqa: BLE001
            log.exception("ask failed")
            return f"Sorry, I couldn't answer that ({type(e).__name__}: {e})."
        return text + _unverified_note(text, seen)

    async def triage(self, alert: dict) -> Triage:
        labels, ann = alert.get("labels", {}), alert.get("annotations", {})
        prompt = (
            f"TRIAGE ALERT alertname={labels.get('alertname')} service={labels.get('service')} "
            f"severity={labels.get('severity')} summary={ann.get('summary', '')!r} "
            f"started={alert.get('startsAt', '')}"
        )
        try:
            text, seen = await asyncio.wait_for(
                self._run(SYSTEM_PROMPT + TRIAGE_SUFFIX, prompt), self.timeout_s
            )
        except Exception as e:  # noqa: BLE001 - an incident must still be posted
            log.exception("triage failed")
            return Triage(
                summary=f"{labels.get('alertname')} on {labels.get('service')} "
                f"(automated triage failed: {type(e).__name__})",
                severity=labels.get("severity", "warning"),
            )
        return parse_triage(text, seen, labels.get("severity", "warning"))

    async def summarize(self, incident_desc: str) -> str:
        return await self.ask(f"Summarize this incident for a status update: {incident_desc}")


def _numbers(text: str) -> set[str]:
    text = re.sub(r"\b5xx\b|\bp\d{2}\b", "", text, flags=re.I)  # 5xx / p95 are names, not values
    return {n.rstrip(".") for n in re.findall(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?", text)}


def _unverified_note(text: str, seen: str) -> str:
    bad = _numbers(text) - _numbers(seen)
    return (
        f"\n_(unverified numbers not found in tool output: {', '.join(sorted(bad))})_"
        if bad
        else ""
    )


def parse_triage(text: str, tool_output: str, default_severity: str) -> Triage:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        d = {}
    if not d:
        return Triage(summary=text.strip()[:500] or "no summary", severity=default_severity)
    seen = _numbers(tool_output)
    evidence = [
        e if _numbers(e) <= seen else f"{e} (unverified: not in tool output)"
        for e in map(str, d.get("evidence", []))
    ]
    return Triage(
        summary=str(d.get("summary", "")),
        likely_cause=str(d.get("likely_cause", "")),
        evidence=evidence,
        runbook_title=str(d.get("runbook_title", "")),
        runbook_url=str(d.get("runbook_url", "")),
        severity=str(d.get("severity") or default_severity),
    )
