"""Registo de execuções: memória + runs/<id>/result.json (consultável após reinício) — CPS 7.9."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from qagent.config import Settings
from qagent.llm import LlmParams
from qagent.models import TERMINAL, ExecutionResult, Progress, StepResult, TestExecutionInput
from qagent.normalizer import from_gherkin
from qagent.orchestrator import Execution, now_iso, request_for_disk, resolve_test_data, run_execution


_RUN_ID_RE = re.compile(r"[0-9a-f]{12}")


class Registry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.items: dict[str, Execution] = {}
        # G3: um bloqueio por dispositivo (udid); "" = sem dispositivo identificado.
        self.device_locks: dict[str, asyncio.Lock] = {}

    def prune_old_runs(self, now: datetime | None = None) -> list[str]:
        """G6: retenção. Só pastas de execução (id de 12 hex) com result.json TERMINADO há mais de
        runs_retention_days; nunca as em curso, as ilegíveis ou as pastas das fases."""
        days = self.settings.runs_retention_days
        if days <= 0:
            return []
        limit = (now or datetime.now(timezone.utc)) - timedelta(days=days)
        removed = []
        for d in self.settings.runs_dir.iterdir():
            f = d / "result.json"
            if not (d.is_dir() and _RUN_ID_RE.fullmatch(d.name) and f.is_file()):
                continue
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
                finished = datetime.fromisoformat(r["finishedAt"].replace("Z", "+00:00"))
            except Exception:  # noqa: BLE001 — sem data fiável → manter
                continue
            if r.get("status") in TERMINAL and finished < limit:
                shutil.rmtree(d, ignore_errors=True)
                removed.append(d.name)
        return removed

    def load_from_disk(self) -> int:
        n = 0
        for f in self.settings.runs_dir.glob("*/result.json"):
            try:
                result = ExecutionResult.model_validate(json.loads(f.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001 — pastas de outras fases (f0/f1) ou ficheiros corrompidos
                continue
            if result.status not in TERMINAL:
                result.status = "error"
                result.summary = "Execução interrompida por reinício do QAgent."
                result.progress.message = "error"
            ex = Execution(result, f.parent)
            if result.status == "error" and "reinício" in result.summary:
                ex.save()
            self.items[result.execution_id] = ex
            n += 1
        return n

    def create(self, req: TestExecutionInput, llm_params: LlmParams | None = None) -> Execution:
        """Valida segredos e cria a execução. Lança SecretError antes de criar qualquer pasta."""
        test_data, secrets = resolve_test_data(req.test_data)
        if llm_params and llm_params.api_key:
            secrets.add(llm_params.api_key)  # mascarar também em erros do provider
        eid = uuid.uuid4().hex[:12]
        run_dir = self.settings.runs_dir / eid
        run_dir.mkdir(parents=True)
        # Texto livre: passos só são conhecidos depois da normalização (no grafo).
        effective = req.steps or (from_gherkin(req.scenario) if req.scenario else [])
        steps = [StepResult(id=i, name=s.name or _default_name(s)) for i, s in enumerate(effective, 1)]
        result = ExecutionResult(
            execution_id=eid, record_id=eid, platform=req.platform, created_at=now_iso(),
            steps=steps, progress=Progress(total_steps=len(steps), message="queued"),
            mode="llm" if not req.steps or any(s.action == "ai" for s in req.steps) else "structured",
        )
        (run_dir / "request.json").write_text(request_for_disk(req), encoding="utf-8")
        ex = Execution(result, run_dir, req, secrets, test_data, llm_params)
        ex.add_artifact("request.json")
        ex.save()
        self.items[eid] = ex
        ex.task = asyncio.create_task(run_execution(ex, self.settings, self.lock_for), name=f"exec-{eid}")
        return ex

    def lock_for(self, udid: str) -> asyncio.Lock:
        return self.device_locks.setdefault(udid, asyncio.Lock())

    def get(self, eid: str) -> Execution | None:
        return self.items.get(eid)

    def list(self) -> list[Execution]:
        return sorted(self.items.values(), key=lambda e: e.result.created_at, reverse=True)

    def resume(self, eid: str) -> bool:
        ex = self.items.get(eid)
        if not ex or ex.result.status != "waiting_for_user" or ex.human_event is None:
            return False
        ex.human_event.set()
        return True

    def stop(self, eid: str) -> bool:
        ex = self.items.get(eid)
        if not ex or not ex.task or ex.task.done():
            return False
        ex.task.cancel()
        return True

    async def shutdown(self) -> None:
        tasks = [e.task for e in self.items.values() if e.task and not e.task.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def _default_name(step) -> str:
    if step.action == "ai":
        return step.text.strip()[:120]
    target = f" {step.locator.value!r}" if step.locator else ""
    text = f" = {step.text!r}" if step.action == "assert_text" else ""
    return f"{step.action}{target}{text}"


def artifact_path(ex: Execution, name: str) -> Path | None:
    """Só nomes da lista de artefactos da execução; sem separadores → sem path traversal."""
    if name not in ex.result.artifacts or "/" in name or "\\" in name or ".." in name:
        return None
    p = (ex.run_dir / name).resolve()
    if p.parent != ex.run_dir.resolve() or not p.is_file():
        return None
    return p
