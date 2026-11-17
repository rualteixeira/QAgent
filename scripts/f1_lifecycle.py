"""Prova de ciclo de vida: N × (ligar MCP → create → screenshot → delete → fechar).

Critério de sucesso: 10 ciclos sem sessões órfãs; sessão MCP única por execução.

Uso:
    uv run python scripts/f1_lifecycle.py --cycles 1
    uv run python scripts/f1_lifecycle.py --cycles 10 --no-reset
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from qagent.appium_session import AppiumSession
from qagent.config import get_settings
from qagent.mcp_client import LLM_TOOL_ALLOWLIST, McpConnection

APP_PACKAGE = "com.saucelabs.mydemoapp.android"


def ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


async def one_cycle(i: int, settings, caps: dict, run_dir: Path) -> dict:
    rec: dict = {"cycle": i, "ok": False, "checks": {}, "timings_ms": {}, "error": None}
    t_cycle = time.perf_counter()
    try:
        async with McpConnection(settings, run_dir) as conn:
            rec["timings_ms"]["mcp_connect"] = conn.connect_ms
            rec["mcp_session_id"] = sid_start = conn.mcp_session_id
            rec["server"] = conn.server_info.model_dump() if conn.server_info else None
            rec["tools_total"] = len(conn.tool_names)
            sess = AppiumSession(conn)
            try:
                # Pré-condição: nenhuma sessão Appium herdada nesta sessão MCP.
                rec["checks"]["no_sessions_before"] = not await sess.has_sessions()

                t = time.perf_counter()
                rec["appium_session_id"] = await sess.create_android(caps)
                rec["timings_ms"]["appium_create"] = ms(t)
                rec["udid"] = sess.udid

                # As tools LangChain usam a mesma sessão MCP → veem a sessão Appium criada acima.
                tools = {t.name: t for t in await conn.langchain_tools(
                    LLM_TOOL_ALLOWLIST | {"appium_session_management"})}
                rec["llm_tools_exposed"] = sorted(n for n in tools if n in LLM_TOOL_ALLOWLIST)
                out = await tools["appium_session_management"].ainvoke({"action": "list"})
                rec["checks"]["adapter_reuses_session"] = rec["appium_session_id"] in str(out)

                t = time.perf_counter()
                pkgs = await sess.foreground_packages()
                rec["timings_ms"]["page_source"] = ms(t)
                rec["foreground_packages"] = sorted(pkgs)
                rec["checks"]["app_in_foreground"] = APP_PACKAGE in pkgs and "android" not in pkgs

                t = time.perf_counter()
                shot = await sess.screenshot()
                rec["timings_ms"]["screenshot"] = ms(t)
                dest = run_dir / "screenshots" / f"cycle-{i:02d}.png"
                shutil.copy2(shot, dest)
                rec["screenshot"] = str(dest.relative_to(run_dir))
                rec["checks"]["screenshot_file_ok"] = dest.stat().st_size > 0
            finally:
                t = time.perf_counter()
                await sess.delete()
                rec["timings_ms"]["appium_delete"] = ms(t)
                rec["checks"]["no_sessions_after_delete"] = not await sess.has_sessions()
            rec["checks"]["mcp_session_id_stable"] = conn.mcp_session_id == sid_start
            rec["mcp_calls"] = [
                {k: v for k, v in asdict(c).items() if k in ("name", "ok", "duration_ms")}
                for c in conn.calls
            ]
        rec["ok"] = all(rec["checks"].values())
    except Exception as e:  # noqa: BLE001 — registar e continuar para os ciclos seguintes
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["traceback"] = traceback.format_exc()
    rec["timings_ms"]["cycle_total"] = ms(t_cycle)
    return rec


async def orphan_check(settings) -> dict:
    """Ligação MCP nova, depois de todos os ciclos: não deve existir nenhuma sessão Appium."""
    async with McpConnection(settings) as conn:
        text = await AppiumSession(conn).list_text()
    return {"list_text": text, "no_orphans": "No active sessions" in text}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=10)
    ap.add_argument("--no-reset", action="store_true",
                    help="appium:noReset=true (não reinstala a APK em cada ciclo)")
    args = ap.parse_args()

    settings = get_settings()
    caps = settings.load_capabilities("android")
    if args.no_reset:
        caps["appium:noReset"] = True

    run_dir = settings.runs_dir / "f1" / datetime.now().strftime("%Y%m%d-%H%M%S")
    (run_dir / "screenshots").mkdir(parents=True)

    print(f"F1: {args.cycles} ciclo(s), transporte={settings.mcp_transport}, "
          f"noReset={caps.get('appium:noReset')} → {run_dir}")
    t0 = time.perf_counter()
    cycles = []
    for i in range(1, args.cycles + 1):
        rec = await one_cycle(i, settings, caps, run_dir)
        cycles.append(rec)
        tm = rec["timings_ms"]
        failed = [k for k, v in rec["checks"].items() if not v]
        print(f"  ciclo {i:2d}: {'OK ' if rec['ok'] else 'FALHOU'} "
              f"create={tm.get('appium_create', '-')}ms total={tm['cycle_total']}ms "
              f"mcp={rec.get('mcp_session_id')}"
              + (f" checks_falhados={failed}" if failed else "")
              + (f" erro={rec['error']}" if rec["error"] else ""))

    orphans = await orphan_check(settings)
    passed = sum(c["ok"] for c in cycles)
    sids = [c.get("mcp_session_id") for c in cycles]
    summary = {
        "phase": "F1",
        "started_at": run_dir.name,
        "transport": settings.mcp_transport,
        "mcp_url": settings.mcp_http_url if settings.mcp_transport == "http" else None,
        "noReset": caps.get("appium:noReset"),
        "cycles_requested": args.cycles,
        "cycles_passed": passed,
        "distinct_mcp_sessions": len(set(sids)) if all(sids) else None,
        "orphan_check": orphans,
        "total_ms": ms(t0),
        "verdict": "PASS" if passed == args.cycles and orphans["no_orphans"] else "FAIL",
        "cycles": cycles,
    }
    (run_dir / "result.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                         encoding="utf-8")
    print(f"Resultado: {summary['verdict']} — {passed}/{args.cycles} ciclos, "
          f"órfãs={'não' if orphans['no_orphans'] else 'SIM'}, total={summary['total_ms'] / 1000:.0f}s")
    return 0 if summary["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # consola Windows em cp1252
    sys.exit(asyncio.run(main()))
