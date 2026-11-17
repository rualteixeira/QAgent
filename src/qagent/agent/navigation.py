"""Apps instaladas e abertura de apps (testes com várias apps, identificadas pelo nome). Estado por execução:
cache da lista de apps e apps já abertas (arranque a frio só na 1.ª abertura)."""

from __future__ import annotations

import re

from qagent.agent.errors import ToolMisuse
from qagent.apps import home_package, installed_apps
from qagent.mcp_client import McpConnection, ToolError

# Partes técnicas comuns em nomes de packages (não identificam a app). Nenhuma palavra de língua natural.
_GENERIC_SEGMENTS = {"com", "org", "net", "io", "co", "android", "google", "apps", "app", "mobile", "client"}


def package_matches_step(package: str, instruction: str) -> bool:
    """True se uma palavra do passo (≥4 caracteres, qualquer língua) e uma parte do package se contêm uma à
    outra. Só serve para um aviso ao modelo (nunca recusa): falsos positivos apenas suprimem o aviso."""
    words = {w for w in re.findall(r"\w{4,}", (instruction or "").lower()) if not w.isdigit()}
    parts = {p for p in re.split(r"[._]", package.lower()) if len(p) >= 3 and p not in _GENERIC_SEGMENTS}
    return any(w in p or (len(p) >= 4 and p in w) for w in words for p in parts)


class AppNavigator:
    def __init__(self, conn: McpConnection, session_id: str, udid: str | None) -> None:
        self._conn = conn
        self._sid = session_id
        self._udid = udid
        self.apps: list[str] | None = None  # cache por execução
        self.opened: set[str] = set()  # apps já abertas neste teste
        self._home: str | None | bool = False  # False = ainda não perguntado

    async def home(self) -> str | None:
        """Package do ecrã inicial deste dispositivo (perguntado ao Android uma vez por execução)."""
        if self._home is False:
            self._home = await home_package(self._udid)
        return self._home

    async def installed(self) -> list[str]:
        if self.apps is None:
            self.apps = await installed_apps(self._conn, self._sid, self._udid)
        return self.apps

    async def close(self, package: str) -> bool:
        """Termina a app (como "forçar paragem"; os dados ficam). False se não estava a correr/não existe."""
        try:
            await self._conn.call("appium_app_lifecycle", {"action": "terminate", "id": package, "sessionId": self._sid})
        except ToolError:
            return False
        return True

    async def open(self, package: str, restart: bool) -> bool:
        """Põe a app à frente. Devolve True se foi um arranque a frio. ToolMisuse se não estiver instalada."""
        apps = await self.installed()
        if apps and package not in apps:
            raise ToolMisuse(f"'{package}' is not an installed app. Use list_apps.")
        cold = restart
        if package not in self.opened:
            # 1.ª abertura neste teste → arranque a frio: muitas apps reabrem no último ecrã, o que torna o
            # teste e o script gerado não determinísticos. Reaberturas seguintes ("volta à app X") mantêm o estado.
            cold = True
            self.opened.add(package)
        if cold:
            try:
                await self._conn.call("appium_app_lifecycle",
                                      {"action": "terminate", "id": package, "sessionId": self._sid})
            except ToolError:
                pass  # não estava a correr
        await self._conn.call("appium_app_lifecycle", {"action": "activate", "id": package, "sessionId": self._sid})
        return cold
