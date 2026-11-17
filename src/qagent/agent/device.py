"""Vista do dispositivo para o executor LLM: ecrã atual (refs → elementos), localização de elementos, gestos e
teclas. Guarda o último ecrã lido (as refs do LLM referem-se a ele)."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from qagent.agent.errors import ToolMisuse
from qagent.appium_session import AppiumSession
from qagent.mcp_client import McpConnection, ToolError
from qagent.screen import Screen, UiElement, free_point, parse_screen

ANDROID_KEYCODES = {"enter": 66, "delete": 67, "tab": 61, "search": 84, "escape": 111, "space": 62, "home": 3}
_ELEMENT_ID_RE = re.compile(r"elementId '([^']+)'")


class SessionView:
    """Acesso mínimo à sessão Appium quando não é passada uma AppiumSession (compatibilidade)."""

    def __init__(self, conn: McpConnection, session_id: str) -> None:
        self._s = AppiumSession(conn)
        self._s.session_id = session_id

    async def page_source(self) -> str:
        return await self._s.page_source()

    async def screenshot(self) -> Path:
        return await self._s.screenshot()


class Device:
    def __init__(self, conn: McpConnection, session_id: str, session: AppiumSession | SessionView) -> None:
        self.conn = conn
        self.sid = session_id
        self.session = session
        self.screen: Screen | None = None
        self.xml: str = ""

    # ---------- ecrã ----------

    async def read_screen(self) -> Screen:
        self.xml = await self.session.page_source()
        self.screen = parse_screen(self.xml)
        return self.screen

    def element_at(self, x: int, y: int) -> UiElement | None:
        """Elemento listado mais interior (menor área) que contém o ponto."""
        inside = [e for e in (self.screen.elements if self.screen else [])
                  if e.bounds[0] <= x <= e.bounds[2] and e.bounds[1] <= y <= e.bounds[3]]
        return min(inside, key=lambda e: (e.bounds[2] - e.bounds[0]) * (e.bounds[3] - e.bounds[1]), default=None)

    async def screen_text(self, filter: str | None = None) -> str:
        screen = await self.read_screen()
        text = screen.describe()
        if filter:
            f = filter.lower()
            keep = [ln for ln in text.splitlines()[1:] if f in ln.lower()]
            text = "\n".join([text.splitlines()[0], *keep]) if keep else f"(nothing matches '{filter}')"
        return text

    async def settled_screen(self, before: str | None) -> str:
        """Reler até o ecrã mudar (transições/animações), máx. ~2,5 s."""
        now = before or ""
        for wait in (0.6, 0.8, 1.0):
            await asyncio.sleep(wait)
            now = await self.screen_text()
            if now != before:
                break
        return now

    def describe(self) -> str | None:
        return self.screen.describe() if self.screen else None

    def packages(self) -> set[str]:
        return set(self.screen.packages) if self.screen else set()

    def element(self, ref: str) -> UiElement:
        el = self.screen.by_ref(ref) if self.screen else None
        if not el:
            raise ToolMisuse(f"unknown ref '{ref}' — use refs from the latest screen description")
        return el

    def unobstructed_point(self, el: UiElement) -> tuple[int, int] | None:
        """Ponto livre do elemento se o centro estiver tapado por outro elemento clicável; None se não estiver."""
        others = [o.bounds for o in (self.screen.elements if self.screen else []) if o is not el and o.clickable]
        return free_point(el.bounds, others)

    # ---------- ações ----------

    async def find(self, el: UiElement) -> str | None:
        """elementId pelo locator estável; None se só houver coordenadas ou se o locator falhar."""
        if not el.locator or el.locator.strategy == "coordinates":
            return None
        try:
            res = await self.conn.call("appium_find_element", {
                "strategy": el.locator.strategy, "selector": el.locator.value, "sessionId": self.sid})
        except ToolError:
            return None
        m = _ELEMENT_ID_RE.search(res.text)
        return m.group(1) if m else None

    async def gesture(self, args: dict) -> None:
        await self.conn.call("appium_gesture", {**args, "sessionId": self.sid})

    async def set_value(self, args: dict) -> None:
        await self.conn.call("appium_set_value", {**args, "sessionId": self.sid})

    async def key(self, key: str) -> None:
        if key == "back":
            await self.gesture({"action": "back"})
        elif key == "hide_keyboard":
            try:
                await self.conn.call("appium_mobile_keyboard", {"action": "hide", "sessionId": self.sid})
            except ToolError:
                pass  # teclado já escondido
        else:
            await self.conn.call("appium_mobile_press_key", {"keyCode": ANDROID_KEYCODES[key], "sessionId": self.sid})

    async def screenshot(self) -> Path:
        return await self.session.screenshot()
