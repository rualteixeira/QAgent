"""N execuções seguidas de um pedido, para medir estabilidade, custo/tempo e locators.

Uso: python scripts/f5_batch.py examples/ca2-texto-livre-login.json --runs 10 [--provider azure] [--label baseline]
Grava runs/f5/<timestamp>-<label>/summary.json. A chave LLM vem das variáveis de utilizador (nunca impressa).
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from run_case import llm_headers  # noqa: E402
from f2_step import user_env  # noqa: E402

GOOD = {"accessibility id", "id", "-android uiautomator"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("request_file")
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--provider", choices=["azure", "gemini"], default="azure")
    ap.add_argument("--api", default="http://127.0.0.1:8100")
    ap.add_argument("--label", default="run")
    args = ap.parse_args()

    body = json.loads(Path(args.request_file).read_text(encoding="utf-8"))
    headers = {"X-API-Key": user_env("QAGENT_DEV_API_KEY", "dev-key"), **llm_headers(args.provider)}
    out_dir = Path("runs/f5") / f"{datetime.now():%Y%m%d-%H%M%S}-{args.label}"
    out_dir.mkdir(parents=True)
    rows = []
    for n in range(1, args.runs + 1):
        t0 = time.time()
        r = httpx.post(f"{args.api}/mobile/testExecution", params={"wait": "true", "waitTimeoutSec": 900},
                       json=body, headers=headers, timeout=960)
        res = r.json() if r.status_code in (200, 202) else {"status": f"http_{r.status_code}"}
        acts = [a for s in res.get("steps", []) for a in s.get("actions", []) if a.get("strategy")]
        good = sum(a["strategy"] in GOOD for a in acts)
        frag = sum(1 for s in res.get("steps", []) for l in s.get("locators", []) if l.get("fragile"))
        xpath_abs = sum(1 for a in acts if a["strategy"] == "xpath" and str(a.get("selector", "")).startswith("/"))
        bad = next((s for s in res.get("steps", []) if s["status"] in ("failed", "error")), None)
        row = {
            "n": n, "executionId": res.get("executionId"), "status": res.get("status"),
            "durationMs": res.get("durationMs"), "steps": len(res.get("steps", [])),
            **{k: res.get("metrics", {}).get(k) for k in ("llmCalls", "tokensIn", "tokensOut", "toolCalls")},
            "locatorActions": len(acts), "goodLocatorActions": good, "fragileLocators": frag, "xpathAbsolute": xpath_abs,
            "failure": (f"passo {bad['id']} [{bad['status']}] {bad['name']}: {bad['reason'][:200]}" if bad else None),
            "wallS": round(time.time() - t0, 1),
        }
        rows.append(row)
        print(f"{n:2d}. {row['status']:9s} {row['durationMs'] and row['durationMs'] / 1000:5.0f}s "
              f"steps={row['steps']} llm={row['llmCalls']} tok={row['tokensIn']}/{row['tokensOut']} "
              f"loc={good}/{len(acts)}" + (f" | {row['failure'][:110]}" if row["failure"] else ""), flush=True)
        (out_dir / "summary.json").write_text(json.dumps({"rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")

    ok = [r for r in rows if r["status"] == "passed"]
    num = lambda k: [r[k] for r in rows if isinstance(r.get(k), (int, float))]  # noqa: E731
    tot_loc = sum(r["locatorActions"] for r in rows)
    summary = {
        "request": args.request_file, "provider": args.provider, "runs": args.runs,
        "passed": len(ok), "CA5_pass": len(ok) >= 8 * args.runs / 10,
        "avg": {k: round(st.mean(num(k))) for k in ("durationMs", "llmCalls", "tokensIn", "tokensOut", "toolCalls") if num(k)},
        "median_durationMs": round(st.median(num("durationMs"))) if num("durationMs") else None,
        "goodLocatorPct": round(100 * sum(r["goodLocatorActions"] for r in rows) / tot_loc, 1) if tot_loc else None,
        "xpathAbsolute": sum(r["xpathAbsolute"] for r in rows),
        "failures": [r["failure"] for r in rows if r["failure"]],
        "rows": rows,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nPASSED {len(ok)}/{args.runs} (CA5 {'OK' if summary['CA5_pass'] else 'FALHA'}) | médias: {summary['avg']} | "
          f"locators bons: {summary['goodLocatorPct']}% | xpath absoluto: {summary['xpathAbsolute']} → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
