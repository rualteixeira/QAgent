"""Catálogo de apps do dispositivo (testes que referem apps pelo nome e mudam de app a meio).

Só as apps com ícone no launcher (MAIN/LAUNCHER) — a lista completa do appium-mcp tem centenas de
packages internos (providers, overlays…). Requer adb local; para dispositivos remotos (F6) cai para a
lista do appium-mcp com um filtro heurístico.
"""

from __future__ import annotations

import asyncio
import json
import shutil

from qagent.mcp_client import McpConnection, ToolError

_NON_UI_HINTS = (".providers.", "overlay", "auto_generated_rro", "io.appium.", ".provider", "android.ext.",
                 "com.android.server.", "com.android.internal.")


async def _adb_launchable(udid: str | None) -> list[str] | None:
    exe = shutil.which("adb")
    if not exe:
        return None
    args = [exe, *(["-s", udid] if udid else []), "shell", "cmd", "package", "query-activities", "--brief",
            "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER"]
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), 15)
    except asyncio.TimeoutError:
        proc.kill()
        return None
    if proc.returncode != 0:
        return None
    pkgs = []
    for line in out.decode(errors="replace").splitlines():
        line = line.strip()
        if "/" in line:
            pkg = line.split("/", 1)[0]
            if pkg not in pkgs:
                pkgs.append(pkg)
    return pkgs or None


async def home_package(udid: str | None) -> str | None:
    """App de ecrã inicial (launcher) do dispositivo, perguntada ao Android (intent HOME) — genérico para qualquer
    fabricante, ao contrário de procurar "launcher" no nome do package. None sem adb/dispositivo remoto."""
    exe = shutil.which("adb")
    if not exe:
        return None
    args = [exe, *(["-s", udid] if udid else []), "shell", "cmd", "package", "resolve-activity", "--brief",
            "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME"]
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), 10)
    except asyncio.TimeoutError:
        proc.kill()
        return None
    lines = [ln.strip() for ln in out.decode(errors="replace").splitlines() if "/" in ln]
    return lines[-1].split("/", 1)[0] if proc.returncode == 0 and lines else None


async def installed_apps(conn: McpConnection, session_id: str, udid: str | None) -> list[str]:
    pkgs = await _adb_launchable(udid)
    if pkgs is not None:
        return sorted(pkgs)
    try:
        res = await conn.call("appium_app_lifecycle", {"action": "list", "sessionId": session_id})
        data = json.loads(res.text[res.text.index("["): res.text.rindex("]") + 1])
        pkgs = [d["packageName"] for d in data]
    except (ToolError, ValueError, KeyError):
        return []
    return sorted(p for p in pkgs if not any(h in p for h in _NON_UI_HINTS))
