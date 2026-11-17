"""Ciclo de vida determinístico da sessão Appium, gerido pelo orquestrador.

As sessões Appium são globais no servidor appium-mcp: depois de criada,
todas as chamadas passam o `sessionId` explicitamente.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from qagent.mcp_client import McpConnection, ToolError

_SESSION_ID_RE = re.compile(r"with ID:\s*([0-9a-fA-F-]{8,})")
_SCREENSHOT_RE = re.compile(r"saved successfully to:\s*(.+\.png)", re.IGNORECASE)
_NO_SESSIONS = "No active sessions"
SYSTEM_PACKAGES = frozenset({"android", "com.android.systemui"})


class AppiumSession:
    def __init__(self, conn: McpConnection) -> None:
        self._conn = conn
        self.session_id: str | None = None
        self.udid: str | None = None

    def _sid(self) -> dict:
        return {"sessionId": self.session_id} if self.session_id else {}

    async def create_android(self, capabilities: dict, udid: str | None = None) -> str:
        args = {"platform": "android"}
        if udid:
            args["deviceUdid"] = udid
        sel = await self._conn.call("select_device", args)
        try:
            hint = json.loads(sel.text).get("capabilities", {})
        except json.JSONDecodeError as e:
            # Mais de um dispositivo → o appium-mcp pede escolha; indicar device.udid.
            raise ToolError(f"select_device não selecionou um dispositivo: {sel.text[:300]}") from e
        self.udid = hint.get("appium:udid") or udid
        caps = {**capabilities, **hint}
        res = await self._conn.call(
            "appium_session_management",
            {"action": "create", "platform": "android", "capabilities": json.dumps(caps)},
            timeout_s=240,
        )
        m = _SESSION_ID_RE.search(res.text)
        if not m:
            raise ToolError(f"id da sessão não encontrado: {res.text[:300]}")
        self.session_id = m.group(1)
        return self.session_id

    async def delete(self) -> None:
        if not self.session_id:
            return
        await self._conn.call(
            "appium_session_management", {"action": "delete", "sessionId": self.session_id}
        )
        self.session_id = None

    async def list_text(self) -> str:
        return (await self._conn.call("appium_session_management", {"action": "list"})).text

    async def has_sessions(self) -> bool:
        return _NO_SESSIONS not in await self.list_text()

    async def screenshot(self) -> Path:
        res = await self._conn.call("appium_screenshot", {"maxWidth": 400, **self._sid()})
        m = _SCREENSHOT_RE.search(res.text)
        if not m:
            raise ToolError(f"caminho do screenshot não encontrado: {res.text[:300]}")
        return Path(m.group(1).strip())

    async def page_source(self) -> str:
        """XML completo do ecrã (vem embrulhado em markdown: '…```xml <?xml…</hierarchy>```')."""
        res = await self._conn.call("appium_get_page_source", self._sid())
        start, end = res.text.find("<"), res.text.rfind(">")
        if start < 0 or end < start:
            raise ToolError(f"page source sem XML: {res.text[:300]}")
        return res.text[start : end + 1]

    @staticmethod
    def packages_in(xml: str) -> set[str]:
        root = ET.fromstring(xml)
        return {el.attrib["package"] for el in root.iter() if el.attrib.get("package")}

    @staticmethod
    def visible_texts(xml: str, limit: int = 10, max_len: int = 120) -> list[str]:
        """Textos visíveis (sem duplicados, sem campos password) — para explicar falhas no relatório."""
        out: list[str] = []
        for el in ET.fromstring(xml).iter():
            t = (el.attrib.get("text") or "").strip()
            if (not t or el.attrib.get("password") == "true" or el.attrib.get("displayed") == "false"
                    or set(t) <= {"•", "*"} or t in out):
                continue
            out.append(t[:max_len])
            if len(out) >= limit:
                break
        return out

    async def foreground_packages(self) -> set[str]:
        """Packages no ecrã. Só pacotes de sistema = diálogo de sistema (ex.: ANR)."""
        return self.packages_in(await self.page_source())
