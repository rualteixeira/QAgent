"""Executor de passo com LLM. Critério de sucesso: passo executado em >= 4/5 tentativas; tokens medidos.

Cada tentativa: sessão Appium nova → pré-condição determinística (ecrã de login) → passos NL com o LLM.

Uso:
    python scripts/f2_step.py --provider gemini --attempts 5 [--model gemini-2.5-flash]
    python scripts/f2_step.py --provider azure --attempts 5  # deployment/endpoint/versão: QAGENT_DEV_AZURE_*
Chaves: QAGENT_DEV_GEMINI_KEY / QAGENT_DEV_AZURE_KEY (ambiente do processo ou variável de utilizador do Windows).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime


from qagent.ai_executor import AiStepExecutor
from qagent.appium_session import AppiumSession
from qagent.config import get_settings
from qagent.executor import StepFailed, StructuredExecutor
from qagent.llm import DEFAULT_MODELS, LlmParams, build_llm
from qagent.mcp_client import McpConnection
from qagent.models import StepResult, StructuredStep
from qagent.runlog import RunLog

logging.getLogger("mcp.client.streamable_http").setLevel(logging.ERROR)

UI = "-android uiautomator"
PRECONDITION = [  # até ao ecrã de login (determinístico, sem LLM)
    {"action": "tap", "locator": {"strategy": "accessibility id", "value": "View menu"}},
    {"action": "scroll_to", "locator": {"strategy": UI, "value": 'new UiSelector().text("Log In")'}},
    {"action": "tap", "locator": {"strategy": UI, "value": 'new UiSelector().text("Log In")'}},
]
NL_STEPS = [
    "Faz login com o utilizador {{testData.username}} e a password {{testData.password}}",
    "Valida que o catálogo de produtos é apresentado",
]
TEST_DATA = {"username": "bod@example.com", "password": "10203040"}


def user_env(name: str, default: str | None = None) -> str | None:
    """Ambiente do processo ou variável de utilizador do Windows (sem reiniciar o terminal)."""
    val = os.environ.get(name)
    if not val and sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                val = winreg.QueryValueEx(k, name)[0]
        except OSError:
            pass
    return (val or "").strip() or default




async def attempt(n: int, settings, params: LlmParams, run_dir) -> dict:
    rec: dict = {"attempt": n, "ok": False, "steps": [], "error": None}
    t0 = time.perf_counter()
    log = RunLog(run_dir / f"attempt-{n:02d}.log", {TEST_DATA["password"], params.api_key or "~~"})
    try:
        async with McpConnection(settings, run_dir) as conn:
            sess = AppiumSession(conn)
            try:
                await sess.create_android(settings.load_capabilities("android"))
                structured = StructuredExecutor(conn, sess.session_id, TEST_DATA)
                for s in PRECONDITION:
                    await structured.run(StructuredStep.model_validate(s), StepResult(id=0, name="pre"))
                llm = build_llm(params)
                ai = AiStepExecutor(conn, sess.session_id, structured, llm, TEST_DATA,
                                    secret_keys={"password"}, max_actions=8, session=sess)
                for i, text in enumerate(NL_STEPS, 1):
                    sr = StepResult(id=i, name=text)
                    ts = time.perf_counter()
                    try:
                        await asyncio.wait_for(ai.run_instruction(text, sr), timeout=240)
                        sr.status = "passed"
                    except StepFailed as e:
                        sr.status, sr.reason = "failed", str(e)
                    except Exception as e:  # noqa: BLE001
                        sr.status, sr.reason = "error", f"{type(e).__name__}: {str(e)[:300]}"
                    step = {"step": i, "status": sr.status, "reason": log.mask(sr.reason),
                            "ms": int((time.perf_counter() - ts) * 1000), "tokens": sr.tokens,
                            "actions": [f"{a.tool}({a.strategy}={a.selector})→{a.result}" for a in sr.actions],
                            "locators": [f"{l.strategy}: {l.value}" for l in sr.locators]}
                    rec["steps"].append(step)
                    log.write("step", **step)
                    if sr.status != "passed":
                        break
                rec["llm_calls"], rec["tokens_in"], rec["tokens_out"] = ai.llm_calls, ai.tokens_in, ai.tokens_out
                rec["ok"] = len(rec["steps"]) == len(NL_STEPS) and all(s["status"] == "passed" for s in rec["steps"])
            finally:
                await sess.delete()
    except Exception as e:  # noqa: BLE001
        rec["error"] = log.mask(f"{type(e).__name__}: {str(e)[:300]}")
    rec["ms"] = int((time.perf_counter() - t0) * 1000)
    return rec


async def main() -> int:
    ap = argparse.ArgumentParser()
    # Sem provider "fake" aqui: o ciclo com LLM simulado está em tests/test_executor_loop.py.
    ap.add_argument("--provider", choices=["gemini", "azure"], default="azure")
    ap.add_argument("--model", default=None)
    ap.add_argument("--attempts", type=int, default=5)
    args = ap.parse_args()

    key = endpoint = api_version = None
    model = args.model or DEFAULT_MODELS.get(args.provider)
    if args.provider in ("gemini", "azure"):
        var = "QAGENT_DEV_GEMINI_KEY" if args.provider == "gemini" else "QAGENT_DEV_AZURE_KEY"
        key = user_env(var)
        if not key:
            print(f"Defina {var} (variável de utilizador do Windows).")
            return 2
    if args.provider == "azure":
        endpoint = user_env("QAGENT_DEV_AZURE_ENDPOINT")
        api_version = user_env("QAGENT_DEV_AZURE_API_VERSION")
        model = args.model or user_env("QAGENT_DEV_AZURE_DEPLOYMENT")
        missing = [v for v, x in (("QAGENT_DEV_AZURE_ENDPOINT", endpoint), ("QAGENT_DEV_AZURE_DEPLOYMENT", model),
                                  ("QAGENT_DEV_AZURE_API_VERSION", api_version)) if not x]
        if missing:
            print(f"Defina as variáveis de utilizador: {', '.join(missing)}")
            return 2
    params = LlmParams(args.provider, model, key, endpoint, api_version)
    settings = get_settings()
    run_dir = settings.runs_dir / "f2" / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True)
    print(f"F2: {args.attempts} tentativa(s), {params.provider}/{params.model} → {run_dir}")

    attempts = []
    for n in range(1, args.attempts + 1):
        rec = await attempt(n, settings, params, run_dir)
        attempts.append(rec)
        steps = " | ".join(f"{s['status']} {s['ms'] / 1000:.1f}s tok={s['tokens']}" for s in rec["steps"])
        print(f"  tentativa {n}: {'OK ' if rec['ok'] else 'FALHOU'} {rec['ms'] / 1000:.0f}s "
              f"llm={rec.get('llm_calls')} [{steps}]" + (f" erro={rec['error']}" if rec["error"] else ""))
        for s in rec["steps"]:
            if s["status"] != "passed":
                print(f"      passo {s['step']}: {s['reason']}")

    ok = sum(a["ok"] for a in attempts)
    done = [a for a in attempts if a.get("llm_calls")]
    summary = {
        "phase": "F2", "llm": params.describe(), "attempts": args.attempts, "passed": ok,
        "verdict": "PASS" if ok >= max(1, round(args.attempts * 0.8)) else "FAIL",
        "avg_llm_calls": round(sum(a["llm_calls"] for a in done) / len(done), 1) if done else None,
        "avg_tokens_in": round(sum(a["tokens_in"] for a in done) / len(done)) if done else None,
        "avg_tokens_out": round(sum(a["tokens_out"] for a in done) / len(done)) if done else None,
        "results": attempts,
    }
    (run_dir / "result.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Resultado: {summary['verdict']} — {ok}/{args.attempts}; média por tentativa: "
          f"{summary['avg_llm_calls']} chamadas LLM, {summary['avg_tokens_in']} tokens in, "
          f"{summary['avg_tokens_out']} tokens out")
    return 0 if summary["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
