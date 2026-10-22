"""MCP client: spawns the three stdio servers and exposes their tools to the LLM."""

import logging
import os
import sys
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.metrics import TOOL_CALLS

log = logging.getLogger("opspilot.mcp")

SERVER_MODULES = [
    "mcp_servers.metrics_server",
    "mcp_servers.logs_server",
    "mcp_servers.runbooks_server",
]


class ToolHub:
    def __init__(self, modules: list[str] | None = None) -> None:
        self.modules = modules or SERVER_MODULES
        self._stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}  # tool name -> owning session
        self._defs: list[dict] = []

    async def start(self) -> None:
        for module in self.modules:
            params = StdioServerParameters(
                command=sys.executable, args=["-m", module], env={**os.environ}
            )
            r, w = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(r, w))
            await session.initialize()
            for t in (await session.list_tools()).tools:
                self._sessions[t.name] = session
                self._defs.append(
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "input_schema": t.inputSchema,
                    }
                )
            log.info("mcp server ready: %s", module)

    async def close(self) -> None:
        await self._stack.aclose()

    def tools(self) -> list[dict]:
        return self._defs

    async def call(self, name: str, args: dict) -> str:
        """Run a tool; failures come back as 'ERROR: ...' text so the agent can react."""
        session = self._sessions.get(name)
        if session is None:
            TOOL_CALLS.labels(name, "unknown").inc()
            return f"ERROR: unknown tool {name}"
        try:
            res = await session.call_tool(name, args)
        except Exception as e:  # noqa: BLE001 - surface any transport/validation error to the model
            TOOL_CALLS.labels(name, "error").inc()
            return f"ERROR: {e}"
        text = "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")
        TOOL_CALLS.labels(name, "error" if res.isError else "ok").inc()
        return f"ERROR: {text}" if res.isError else text
