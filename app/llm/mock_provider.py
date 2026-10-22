"""Deterministic provider for tests/CI/offline demos.

Turn 1: requests tools based on the prompt. Turn 2: writes the answer using ONLY tool output.
"""

import json
import re

from app.llm.base import LLMReply, ToolCall, Usage

ERR_RATIO = (
    'round(sum(rate(http_requests_total{status=~"5.."}[1m]))'
    " / sum(rate(http_requests_total[1m])), 0.001)"
)
P95 = (
    "round(histogram_quantile(0.95, sum by (le) "
    "(rate(http_request_duration_seconds_bucket[1m]))), 0.001)"
)
UP = 'up{job="checkout"}'


def _first_user(messages: list[dict]) -> str:
    return next(m["content"] for m in messages if m["role"] == "user")


def _results(messages: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for m in messages:
        if m["role"] == "tool":
            for r in m["results"]:
                out.setdefault(r["name"], []).append(r["content"])
    return out


def _value(line: str) -> str | None:
    m = re.search(r"=> (\S+)", line)
    return m.group(1) if m else None


class MockProvider:
    name = "mock"

    async def chat(self, system: str, messages: list[dict], tools: list[dict]) -> LLMReply:
        usage = Usage(input_tokens=len(str(messages)) // 4, output_tokens=120)
        prompt = _first_user(messages)
        res = _results(messages)
        if not res:
            return LLMReply(tool_calls=self._plan(prompt), usage=usage)
        if prompt.startswith("TRIAGE ALERT"):
            return LLMReply(text=self._triage(prompt, res), usage=usage)
        return LLMReply(text=self._answer(res), usage=usage)

    def _plan(self, prompt: str) -> list[ToolCall]:
        text = prompt.lower()
        calls = [
            ToolCall("m1", "prom_query", {"query": ERR_RATIO}),
            ToolCall("m2", "prom_query", {"query": P95}),
            ToolCall("m3", "search_logs", {"minutes": 10, "level": "ERROR", "limit": 3}),
            ToolCall("m4", "search_runbooks", {"query": prompt[:200]}),
        ]
        if "down" in text:
            calls.insert(2, ToolCall("m5", "prom_query", {"query": UP}))
        return calls

    def _facts(self, res: dict[str, list[str]]) -> dict:
        prom = res.get("prom_query", [])
        logs = json.loads(res["search_logs"][0]) if "search_logs" in res else {}
        try:
            runbooks = json.loads(res["search_runbooks"][0])
        except (KeyError, ValueError):
            runbooks = []
        top = (logs.get("top_messages") or [{}])[0]
        return {
            "err": _value(prom[0]) if prom else None,
            "p95": _value(prom[1]) if len(prom) > 1 else None,
            "log_count": logs.get("matched", 0),
            "top_msg": top.get("msg"),
            "top_count": top.get("count"),
            "sample": (logs.get("latest") or [{}])[-1].get("msg"),
            "runbook": runbooks[0] if runbooks else None,
        }

    def _answer(self, res: dict[str, list[str]]) -> str:
        f = self._facts(res)
        parts = [f"5xx ratio is {f['err']}; p95 latency is {f['p95']}s."]
        if f["log_count"]:
            parts.append(
                f"{f['log_count']} ERROR logs in the last 10m, most frequent: "
                f"'{f['top_msg']}' ({f['top_count']}x)."
            )
        if f["runbook"]:
            parts.append(f"Runbook: {f['runbook']['title']} ({f['runbook']['url']}).")
        return " ".join(parts)

    def _triage(self, prompt: str, res: dict[str, list[str]]) -> str:
        f = self._facts(res)
        name = re.search(r"alertname=(\S+)", prompt)
        sev = re.search(r"severity=(\S+)", prompt)
        service = re.search(r"service=(\S+)", prompt)
        evidence = [f"5xx ratio = {f['err']}", f"p95 latency = {f['p95']}s"]
        if f["top_msg"]:
            evidence.append(f"{f['top_count']}x log: {f['top_msg']}")
        if f["sample"]:
            evidence.append(f"latest error log: {f['sample']}")
        cause = (
            f"Most frequent error log is '{f['top_msg']}'"
            if f["top_msg"]
            else "No error logs found in the last 10 minutes; cause unknown"
        )
        rb = f["runbook"] or {}
        return json.dumps(
            {
                "summary": f"{name.group(1) if name else 'Alert'} on "
                f"{service.group(1) if service else 'service'}: 5xx ratio {f['err']}, "
                f"p95 {f['p95']}s.",
                "likely_cause": cause,
                "evidence": evidence,
                "runbook_title": rb.get("title", ""),
                "runbook_url": rb.get("url", ""),
                "severity": sev.group(1) if sev else "warning",
            }
        )
