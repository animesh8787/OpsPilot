"""Ollama local provider (free fallback)."""

import itertools
from typing import Any

import httpx

from app.llm.base import LLMReply, ToolCall, Usage

DEFAULT_MODEL = "llama3.1"
_ids = itertools.count(1)


def to_ollama_messages(system: str, messages: list[dict]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.get("text", "")}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {"function": {"name": t.name, "arguments": t.args}} for t in m["tool_calls"]
                ]
            out.append(msg)
        else:
            out += [
                {"role": "tool", "tool_name": r["name"], "content": r["content"]}
                for r in m["results"]
            ]
    return out


class OllamaProvider:
    name = "ollama"

    def __init__(
        self, base_url: str, model: str = "", transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.model = model or DEFAULT_MODEL
        self.http = httpx.AsyncClient(base_url=base_url, timeout=120, transport=transport)

    async def chat(self, system: str, messages: list[dict], tools: list[dict]) -> LLMReply:
        body: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "messages": to_ollama_messages(system, messages),
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ]
        r = await self.http.post("/api/chat", json=body)
        r.raise_for_status()
        data = r.json()
        msg = data["message"]
        calls = [
            ToolCall(
                f"ollama-{next(_ids)}", c["function"]["name"], c["function"].get("arguments", {})
            )
            for c in msg.get("tool_calls") or []
        ]
        return LLMReply(
            text=msg.get("content", ""),
            tool_calls=calls,
            usage=Usage(data.get("prompt_eval_count", 0), data.get("eval_count", 0)),
        )
