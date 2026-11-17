"""/health (com cache) e /mobile/devices."""

from __future__ import annotations

import asyncio
import re
import shutil
import time

from qagent.config import Settings
from qagent.mcp_client import LLM_TOOL_ALLOWLIST, McpConnection

_ORCHESTRATOR_TOOLS = {"select_device", "appium_session_management", "appium_get_page_source"}


async def _run(*cmd: str, timeout: float = 10) -> tuple[int, str]:
    exe = shutil.which(cmd[0])
    if not exe:
        return 127, f"{cmd[0]} não encontrado no PATH"
    proc = await asyncio.create_subprocess_exec(
        exe, *cmd[1:], stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timeout"
    return proc.returncode, out.decode(errors="replace").strip()


async def adb_devices() -> list[dict]:
    rc, out = await _run("adb", "devices", "-l")
    if rc != 0:
        return []
    devices = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        info = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
        devices.append({
            "udid": parts[0], "state": parts[1], "platform": "android",
            "type": "EMULATOR" if parts[0].startswith("emulator-") else "REAL",
            "model": info.get("model"),
        })
    return devices


async def device_precheck(udid: str | None, timeout: float = 10) -> str | None:
    """Falha depressa, com uma mensagem útil, quando o dispositivo não responde (o Appium sozinho demora
    20–240 s e devolve um erro técnico). Devolve None se estiver pronto, senão a explicação."""
    devices = [d for d in await adb_devices() if d["state"] == "device"]
    if not devices:
        return "Nenhum dispositivo Android ligado/pronto (adb devices vazio). Arranque o emulador ou ligue o dispositivo."
    known = [d["udid"] for d in devices]
    if udid and udid not in known:
        return f"O dispositivo {udid} não está ligado (ligados: {', '.join(known)})."
    target = udid or known[0]
    rc, out = await _run("adb", "-s", target, "shell", "getprop", "sys.boot_completed", timeout=timeout)
    if rc == 124:
        return (f"O dispositivo {target} não responde (adb sem resposta em {timeout:g}s): o emulador pode estar "
                "bloqueado — reinicie-o e verifique a memória livre do PC.")
    if rc != 0 or out.strip() != "1":
        return f"O dispositivo {target} ainda não está pronto (sys.boot_completed={out.strip()!r})."
    return None


async def first_ready_device() -> str | None:
    """Dispositivo efetivo quando o pedido não indica udid (para o bloqueio por dispositivo e para que o
    select_device não tenha de escolher)."""
    ready = [d["udid"] for d in await adb_devices() if d["state"] == "device"]
    return ready[0] if ready else None


async def device_props(udid: str) -> dict[str, str]:
    """Versão do Android e modelo (para o relatório). Vazio se o adb não responder."""
    out: dict[str, str] = {}
    for key, prop in (("platformVersion", "ro.build.version.release"), ("model", "ro.product.model")):
        rc, val = await _run("adb", "-s", udid, "shell", "getprop", prop, timeout=5)
        if rc == 0 and val:
            out[key] = val.strip()
    return out


_VERSION_RE = re.compile(r"versionName=(\S+)")


async def app_versions(udid: str, packages: list[str]) -> dict[str, str]:
    """versionName de cada package instalado (genérico: dumpsys package). Ignora os não encontrados."""
    out: dict[str, str] = {}
    for pkg in packages:
        rc, val = await _run("adb", "-s", udid, "shell", "dumpsys", "package", pkg, timeout=8)
        m = _VERSION_RE.search(val) if rc == 0 else None
        if m:
            out[pkg] = m.group(1)
    return out


class HealthChecker:
    def __init__(self, settings: Settings, ttl_s: float = 30) -> None:
        self._settings = settings
        self._ttl = ttl_s
        self._cache: tuple[float, dict] | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> dict:
        async with self._lock:
            if self._cache and time.monotonic() - self._cache[0] < self._ttl:
                return {**self._cache[1], "cached": True}
            data = await self._check()
            self._cache = (time.monotonic(), data)
            return {**data, "cached": False}

    async def _check(self) -> dict:
        s = self._settings
        node_rc, node_out = await _run("node", "--version")
        devices = await adb_devices()
        mcp: dict = {"transport": s.mcp_transport, "pinnedVersion": s.appium_mcp_version}
        try:
            async with McpConnection(s) as conn:
                tools = set(conn.tool_names)
                needed = LLM_TOOL_ALLOWLIST | _ORCHESTRATOR_TOOLS
                mcp.update(ok=True, server=conn.server_info.model_dump() if conn.server_info else None,
                           connectMs=conn.connect_ms, toolsTotal=len(tools),
                           missingTools=sorted(needed - tools))
                version = conn.server_info.version if conn.server_info else None
                mcp["versionMatches"] = version == s.appium_mcp_version
                mcp["ok"] = not mcp["missingTools"] and mcp["versionMatches"]
        except Exception as e:  # noqa: BLE001
            mcp.update(ok=False, error=f"{type(e).__name__}: {e}"[:300])
        checks = {
            "node": {"ok": node_rc == 0, "version": node_out if node_rc == 0 else None},
            "adb": {"ok": shutil.which("adb") is not None,
                    "devices": [d for d in devices if d["state"] == "device"]},
            "appiumMcp": mcp,
        }
        ok = all(c["ok"] for c in checks.values())
        return {"status": "ok" if ok else "degraded", "checks": checks}
