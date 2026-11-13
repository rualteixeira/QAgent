"""Envia um pedido de examples/ à API do QAgent com o LLM das variáveis de utilizador e mostra o relatório.

Uso: python scripts/run_case.py examples/ca2-texto-livre-login.json [--provider azure|gemini] [--api http://127.0.0.1:8100]
Variáveis: QAGENT_DEV_AZURE_{KEY,ENDPOINT,DEPLOYMENT,API_VERSION} ou QAGENT_DEV_GEMINI_KEY; QAGENT_DEV_API_KEY (X-API-Key, omissão dev-key).
A chave LLM vai só no cabeçalho do pedido e nunca é impressa.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from f2_step import user_env  # noqa: E402


def llm_headers(provider: str) -> dict[str, str]:
    if provider == "azure":
        vals = {h: user_env(v) for h, v in (
            ("X-LLM-API-Key", "QAGENT_DEV_AZURE_KEY"), ("X-LLM-Endpoint", "QAGENT_DEV_AZURE_ENDPOINT"),
            ("X-LLM-Model", "QAGENT_DEV_AZURE_DEPLOYMENT"), ("X-LLM-APIVersion", "QAGENT_DEV_AZURE_API_VERSION"))}
    else:
        vals = {"X-LLM-API-Key": user_env("QAGENT_DEV_GEMINI_KEY")}
    missing = [h for h, v in vals.items() if not v]
    if missing:
        sys.exit(f"Variáveis em falta para {provider}: {missing}")
    return {"X-Provider": provider, **vals}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("request_file")
    ap.add_argument("--provider", choices=["azure", "gemini"], default="azure")
    ap.add_argument("--api", default="http://127.0.0.1:8100")
    args = ap.parse_args()
    body = json.loads(Path(args.request_file).read_text(encoding="utf-8"))
    headers = {"X-API-Key": user_env("QAGENT_DEV_API_KEY", "dev-key"), **llm_headers(args.provider)}
    r = httpx.post(f"{args.api}/mobile/testExecution", params={"wait": "true", "waitTimeoutSec": 900},
                   json=body, headers=headers, timeout=960)
    if r.status_code not in (200, 202):
        print(f"HTTP {r.status_code}: {r.text[:500]}")
        return 2
    res = r.json()
    if "steps" not in res:
        print(f"Ainda a correr: {res}")
        return 1
    m = res["metrics"]
    print(f"{res['executionId']} {res['status'].upper()} {res['durationMs'] / 1000:.0f}s | LLM {m['llmCalls']} "
          f"chamadas, {m['tokensIn']} in / {m['tokensOut']} out | {m['toolCalls']} tool calls")
    print(f"summary: {res['summary']}")
    for s in res["steps"]:
        locs = ", ".join(f"{l['strategy']}={l['value']}" for l in s["locators"]) or "—"
        shot = s["evidence"].get("screenshot") or "—"
        print(f"  {s['id']}. [{s['status']}] {s['name']}\n     reason: {s['reason']}\n     locators: {locs} | screenshot: {shot}")
    return 0 if res["status"] in ("passed", "failed") else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
