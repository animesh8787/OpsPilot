"""Provider-neutral LLM types.

Conversation messages are plain dicts:
  {"role": "user", "content": str}
  {"role": "assistant", "text": str, "tool_calls": [ToolCall], "raw": provider-specific | None}
  {"role": "tool", "results": [{"id", "name", "content", "is_error"}]}
`raw` lets a provider replay its own assistant turn verbatim (e.g. Claude thinking blocks).
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    raw: Any = None


class LLMProvider(Protocol):
    name: str

    async def chat(
        self, system: str, messages: list[dict], tools: list[dict]
    ) -> LLMReply:  # tools: [{"name", "description", "input_schema"}]
        ...
