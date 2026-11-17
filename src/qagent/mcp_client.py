"""Cliente MCP com uma única sessão persistente por execução.

Uso:
    async with McpConnection(settings, run_dir) as conn:
        result = await conn.call("appium_session_management", {"action": "list"})
"""

from __future__ import annotations

import os
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from qagent.config import Settings

# Ferramentas do appium-mcp que o executor de passo (LLM) pode usar.
# Gestão de sessão, instalação, permissões, ficheiros e preparação iOS ficam no orquestrador.
LLM_TOOL_ALLOWLIST: frozenset[str] = frozenset(
    {
        "appium_find_element",
        "appium_find_elements",
        "appium_get_active_element",
        "appium_gesture",
        "appium_drag_and_drop",
        "appium_set_value",
        "appium_get_text",
        "appium_mobile_keyboard",
        "appium_alert",
        "appium_app_lifecycle",
        "appium_context",
        "appium_screenshot",
        "generate_locators",
    }
)


class ToolError(RuntimeError):
    """A ferramenta MCP devolveu isError=true."""


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    ok: bool
    text: str
    duration_ms: int
    other_content: list[str] = field(default_factory=list)


class McpConnection:
    """Abre o transporte + ClientSession uma vez e reutiliza-os em todas as chamadas."""

    def __init__(self, settings: Settings, run_dir: Path | None = None) -> None:
        self._settings = settings
        self._run_dir = run_dir
        self._stack: AsyncExitStack | None = None
        self._get_session_id = None
        self.session: ClientSession | None = None
        self.server_info: types.Implementation | None = None
        self.tool_names: list[str] = []
        self.calls: list[ToolCall] = []
        self.connect_ms: int = 0

    @property
    def mcp_session_id(self) -> str | None:
        """Id da sessão MCP (só HTTP). Deve manter-se igual durante toda a execução."""
        return self._get_session_id() if self._get_session_id else None

    async def __aenter__(self) -> "McpConnection":
        t0 = time.perf_counter()
        self._stack = AsyncExitStack()
        try:
            if self._settings.mcp_transport == "http":
                read, write, get_sid = await self._stack.enter_async_context(
                    streamable_http_client(self._settings.mcp_http_url)
                )
                self._get_session_id = get_sid
            else:
                read, write = await self._stack.enter_async_context(
                    stdio_client(self._stdio_params())
                )
            self.session = await self._stack.enter_async_context(ClientSession(read, write))
            init = await self.session.initialize()
            self.server_info = init.serverInfo
            tools = await self.session.list_tools()
            self.tool_names = [t.name for t in tools.tools]
        except BaseException:
            await self._stack.aclose()
            raise
        self.connect_ms = int((time.perf_counter() - t0) * 1000)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._stack:
            await self._stack.aclose()

    def _stdio_params(self) -> StdioServerParameters:
        s = self._settings
        env = {
            **os.environ,
            "ANDROID_HOME": s.android_home,
            "ANDROID_SDK_ROOT": s.android_home,
            "JAVA_HOME": s.java_home,
            "CAPABILITIES_CONFIG": str(s.capabilities_config),
            "NO_UI": "true",
            "APPIUM_MCP_ON_CLIENT_DISCONNECT": "delete_all",
            "APPIUM_MCP_EVIDENCE": "true",
            "ALLOW_REMOTE_APP_URLS": "false",
            "AI_VISION_ENABLED": "false",
        }
        if self._run_dir:
            env["SCREENSHOTS_DIR"] = str(self._run_dir / "screenshots")
            env["PAGE_SOURCES_DIR"] = str(self._run_dir / "pagesources")
        return StdioServerParameters(command="node", args=[str(s.appium_mcp_entry)], env=env)

    async def call(
        self, name: str, arguments: dict[str, Any] | None = None, *, timeout_s: float | None = None
    ) -> ToolCall:
        assert self.session, "ligação MCP não aberta"
        args = arguments or {}
        t0 = time.perf_counter()
        result = await self.session.call_tool(
            name, args, read_timeout_seconds=timedelta(seconds=timeout_s) if timeout_s else None
        )
        texts, other = [], []
        for c in result.content:
            if isinstance(c, types.TextContent):
                texts.append(c.text)
            else:
                other.append(c.type)
        call = ToolCall(
            name=name,
            arguments=args,
            ok=not result.isError,
            text="\n".join(texts),
            duration_ms=int((time.perf_counter() - t0) * 1000),
            other_content=other,
        )
        self.calls.append(call)
        if result.isError:
            raise ToolError(f"{name}: {call.text}")
        return call

    async def langchain_tools(self, allowlist: frozenset[str] = LLM_TOOL_ALLOWLIST) -> list[BaseTool]:
        """Ferramentas LangChain ligadas a esta sessão MCP (não abrem sessões novas)."""
        tools = await load_mcp_tools(self.session)
        return [t for t in tools if t.name in allowlist]
