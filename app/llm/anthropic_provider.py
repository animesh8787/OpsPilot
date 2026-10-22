"""Anthropic Claude provider."""

from typing import Any

from anthropic import AsyncAnthropic

from app.llm.base import LLMReply, ToolCall, Usage

DEFAULT_MODEL = "claude-opus-5-5"


def to_anthropic_messages(messages: list[dict]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            if m.get("raw") is not None:
                content = m["raw"]  # replay verbatim so thinking blocks stay valid
            else:
                content = ([{"type": "text", "text": m["text"]}] if m.get("text") else []) + [
                    {"type": "tool_use", "id": t.id, "name": t.name, "input": t.args}
                    for t in m.get("tool_calls", [])
                ]
            out.append({"role": "assistant", "content": content})
        else:
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": r["id"],
                            "content": r["content"],
                            "is_error": r.get("is_error", False),
                        }
                        for r in m["results"]
                    ],
                }
            )
    return out


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "") -> None:
        self.model = model or DEFAULT_MODEL
        self.client = AsyncAnthropic(api_key=api_key or None)

    async def chat(self, system: str, messages: list[dict], tools: list[dict]) -> LLMReply:
        kwargs: dict[str, Any] = {}
        if tools:
            # no forced tool_choice: it is rejected by this model family
            kwargs["tools"] = tools
        resp = await self.client.beta.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=to_anthropic_messages(messages),
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            **kwargs,
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        if resp.stop_reason == "refusal":
            text = text or "The model declined to answer this request."
        calls = [
            ToolCall(b.id, b.name, dict(b.input)) for b in resp.content if b.type == "tool_use"
        ]
        return LLMReply(
            text=text,
            tool_calls=calls,
            usage=Usage(resp.usage.input_tokens, resp.usage.output_tokens),
            raw=resp.content,
        )
