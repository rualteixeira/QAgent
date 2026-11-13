"""Orquestrador de uma execução (CPS 7.1/7.2). Determinístico; o LLM só entra no executor de passo."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from qagent.ai_executor import AiStepExecutor, HumanInputRequired, PreexistingState
from qagent.apps import home_package
from qagent.appium_session import AppiumSession
from qagent.config import Settings
from qagent.executor import StepFailed, StructuredExecutor
from qagent.llm import LlmParams, build_llm
from qagent.mcp_client import McpConnection, ToolError
from qagent.models import ActionRecord, ExecutionResult, StepResult, StructuredStep, TestExecutionInput
from qagent.normalizer import MAX_STEPS, from_free_text, from_gherkin
from qagent.prompts import DEFAULT_NORMALIZER
from qagent.health import app_versions, device_precheck, device_props, first_ready_device
from qagent.runlog import RunLog
from qagent.screen import has_error_dialog

_SECRET_REF_RE = re.compile(r"^\{\{\s*secret:([A-Za-z0-9_]+)\s*\}\}$")
_SENSITIVE_KEY_RE = re.compile(r"pass|secret|token|pwd|pin", re.IGNORECASE)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class SecretError(ValueError):
    pass


class EnvironmentProblem(RuntimeError):
    """Dispositivo/ambiente não está em condições (ex.: emulador bloqueado)."""


class HumanTimeout(RuntimeError):
    """O utilizador não concluiu a ação pedida dentro de humanTimeoutSec."""


class NormalizerError(RuntimeError):
    """Falha a dividir o texto livre em passos (LLM)."""


_ENV_HINTS = ("adb", "timed out", "device", "emulator", "instrumentation", "uiautomation not connected")


def classify_exception(e: BaseException) -> str:
    """Categoria (CA5) de uma exceção fora de um veredicto funcional."""
    if isinstance(e, (EnvironmentProblem, HumanTimeout, asyncio.TimeoutError)):
        return "environment"
    if isinstance(e, NormalizerError):
        return "llm"
    msg = str(e).lower()
    if isinstance(e, ToolError):
        return "environment" if any(h in msg for h in _ENV_HINTS) else "appium_mcp"
    return "appium_mcp" if "mcp" in type(e).__name__.lower() or "mcp" in msg else "environment"



def resolve_test_data(test_data: dict[str, str]) -> tuple[dict[str, str], set[str]]:
    """`{{secret:nome}}` → env QAGENT_SECRET_<NOME>. Devolve (valores, conjunto a mascarar nos logs)."""
    values, secrets = {}, set()
    for key, raw in test_data.items():
        m = _SECRET_REF_RE.match(raw)
        if m:
            env = f"QAGENT_SECRET_{m.group(1).upper()}"
            if env not in os.environ:
                raise SecretError(f"segredo '{m.group(1)}' não configurado (variável {env})")
            values[key] = os.environ[env]
            secrets.add(values[key])
        else:
            values[key] = raw
            if _SENSITIVE_KEY_RE.search(key):
                secrets.add(raw)
    return values, secrets


def build_android_caps(settings: Settings, req: TestExecutionInput) -> dict:
    caps = settings.load_capabilities("android")
    a = req.app.android if req.app else None
    if not a or not (a.app_package or a.app):
        # Sem app no pedido: começar no ecrã inicial do dispositivo; o próprio teste diz que app(s)
        # abrir. "" anula os valores por omissão do QAgent e do CAPABILITIES_CONFIG do appium-mcp.
        caps.update({"appium:app": "", "appium:appPackage": "", "appium:appActivity": "",
                     "appium:noReset": True, "appium:autoLaunch": False})
        return caps
    if a:
        if a.app_package:
            caps["appium:appPackage"] = a.app_package
        if a.app_activity:
            caps["appium:appActivity"] = a.app_activity
        if a.app is not None:
            caps["appium:app"] = a.app
        # Outra app que não a por omissão. NÃO basta omitir as chaves: o appium-mcp junta o seu
        # CAPABILITIES_CONFIG às capabilities do pedido ({...config, ...pedido}) e só depois remove as
        # que valem "" (filterEmptyCapabilities, create-session.js). Enviar "" anula o valor por omissão.
        if a.app_package and not a.app:
            caps["appium:app"] = ""  # app já instalada: não instalar a APK por omissão
        if a.app_package and not a.app_activity:
            caps["appium:appActivity"] = ""  # o UiAutomator2 resolve a activity de arranque sozinho
    return caps


class Execution:
    def __init__(self, result: ExecutionResult, run_dir: Path, request: TestExecutionInput | None = None,
                 secrets: set[str] | None = None, test_data: dict[str, str] | None = None,
                 llm_params: LlmParams | None = None) -> None:
        self.result = result
        self.llm_params = llm_params
        self.llm = None
        self.ai_exec: AiStepExecutor | None = None
        self.human_event: asyncio.Event | None = None  # definido enquanto waiting_for_user
        self.norm_calls = 0
        self.norm_tokens: dict[str, int] = {}
        # Passos efetivos: 'steps' > 'scenario' (Gherkin, sem LLM) > 'testExecution' (normalizado no grafo).
        self.steps: list[StructuredStep] = []
        self.input_kind = "none"
        if request is not None:
            if request.steps:
                self.steps, self.input_kind = list(request.steps), "steps"
            elif request.scenario:
                self.steps, self.input_kind = from_gherkin(request.scenario), "gherkin"
            elif request.test_execution:
                self.input_kind = "free_text"
        self.run_dir = run_dir
        self.request = request
        self.secrets = secrets or set()
        self.test_data = test_data or {}
        self.task: asyncio.Task | None = None
        self.log = RunLog(run_dir / "qagent.log", self.secrets)

    @property
    def id(self) -> str:
        return self.result.execution_id

    def add_artifact(self, name: str) -> None:
        if name not in self.result.artifacts:
            self.result.artifacts.append(name)

    def save(self) -> None:
        tmp = self.run_dir / "result.json.tmp"
        tmp.write_text(self.result.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
        tmp.replace(self.run_dir / "result.json")


def _summary(res: ExecutionResult) -> str:
    total = len(res.steps)
    passed = sum(s.status == "passed" for s in res.steps)
    skipped = sum(s.status == "skipped" for s in res.steps)
    bad = next((s for s in res.steps if s.status in ("failed", "error")), None)
    if res.status == "passed":
        return f"{passed}/{total} passos passaram."
    if res.status == "cancelled":
        return f"Execução cancelada pelo utilizador após {passed}/{total} passos com sucesso."
    if bad:
        kind = "falhou" if bad.status == "failed" else "terminou com erro"
        tail = f" {skipped} passo(s) ignorado(s)." if skipped else ""
        return f"Passo {bad.id} ('{bad.name}') {kind}: {bad.reason}{tail}"
    return res.summary or "Erro de infraestrutura antes dos passos."


async def run_execution(ex: Execution, settings: Settings, lock_for: Callable[[str], asyncio.Lock]) -> None:
    res, req, log = ex.result, ex.request, ex.log
    assert req
    t0 = time.perf_counter()
    conn: McpConnection | None = None
    try:
        res.progress.message = "À espera do dispositivo"
        ex.save()
        # G3: bloqueio POR DISPOSITIVO (CPS 7.3 regra 5). Sem udid no pedido usa-se o 1.º dispositivo pronto, para
        # que um pedido sem udid e outro com o mesmo udid não corram em paralelo no mesmo aparelho.
        udid = req.device.udid or await first_ready_device()
        async with lock_for(udid or ""):
            res.status = "running"
            res.started_at = now_iso()
            res.progress.message = "A verificar o dispositivo"
            ex.save()
            log.write("execution_started", executionId=ex.id, input=ex.input_kind, steps=len(ex.steps), udid=udid)
            problem = await device_precheck(udid)
            if problem:
                raise EnvironmentProblem(problem)  # falha rápida, sem novas tentativas (G1)
            if udid:
                props = await device_props(udid)
                res.device.platform_version, res.device.model = props.get("platformVersion"), props.get("model")
                res.device.home_package = await home_package(udid)
            caps = build_android_caps(settings, req)
            stack, conn, sess = await _connect_with_retries(ex, settings, caps, udid)
            async with stack:
                try:
                    res.device.udid = sess.udid
                    for pkg in req.options.reset_apps:
                        # Estado limpo pedido explicitamente pelo autor do teste (pm clear).
                        try:
                            await conn.call("appium_app_lifecycle",
                                            {"action": "clear", "id": pkg, "sessionId": sess.session_id})
                            log.write("app_reset", package=pkg)
                        except ToolError as e:
                            log.write("app_reset_failed", package=pkg, error=str(e)[:200])
                    main_pkg = req.app.android.app_package if req.app and req.app.android else None
                    if main_pkg and main_pkg in req.options.reset_apps:
                        # G6: limpar os dados fecha a app; a app em teste tem de voltar a abrir (antes era o
                        # noReset=false das capabilities que o fazia).
                        await conn.call("appium_app_lifecycle",
                                        {"action": "activate", "id": main_pkg, "sessionId": sess.session_id})
                        log.write("app_relaunched", package=main_pkg)
                    executor = StructuredExecutor(conn, sess.session_id, ex.test_data)
                    if ex.llm_params:
                        # A API garante llm_params quando há passos 'ai', Gherkin ou texto livre.
                        ex.llm = build_llm(ex.llm_params)
                        ex.ai_exec = AiStepExecutor(
                            conn, sess.session_id, executor, ex.llm, ex.test_data,
                            secret_keys={k for k, v in ex.test_data.items() if v in ex.secrets},
                            max_actions=req.options.max_actions_per_step, session=sess, udid=sess.udid,
                            report_language=req.options.report_language,
                            prompt_version=req.options.prompt_version)
                        res.prompt_versions["executor"] = ex.ai_exec.prompt_version
                        log.write("llm_configured", **ex.llm_params.describe())
                    graph = build_graph(ex, sess, executor)
                    await graph.ainvoke({"index": 0, "stop": False},
                                        config={"recursion_limit": len(ex.steps) + MAX_STEPS * 2 + 10})
                finally:
                    await _cleanup(ex, sess)
                    res.metrics.tool_calls = len(conn.calls)
                    await _record_app_versions(ex, sess.udid or udid)
        statuses = {s.status for s in res.steps}
        res.status = "error" if "error" in statuses else "failed" if "failed" in statuses else "passed"
        if not res.steps:
            res.status, res.summary = "error", "Nenhum passo para executar."
    except asyncio.CancelledError:
        res.status = "cancelled"
        log.write("execution_cancelled")
    except EnvironmentProblem as e:
        res.status, res.failure_category = "error", "environment"
        res.summary = f"Ambiente: {e}"
        log.write("execution_error", error=res.summary, category="environment")
    except Exception as e:  # noqa: BLE001 — erro de infraestrutura (inclui falha do normalizador)
        res.status = "error"
        res.failure_category = classify_exception(e)
        res.summary = log.mask(f"Erro: {type(e).__name__}: {str(e)[:400]}")
        log.write("execution_error", error=res.summary, category=res.failure_category)
    finally:
        if conn is not None:
            res.metrics.tool_calls = len(conn.calls)
        calls = ex.norm_calls
        tin, tout = ex.norm_tokens.get("input", 0), ex.norm_tokens.get("output", 0)
        if ex.ai_exec:
            calls += ex.ai_exec.llm_calls
            tin += ex.ai_exec.tokens_in
            tout += ex.ai_exec.tokens_out
        res.metrics.llm_calls, res.metrics.tokens_in, res.metrics.tokens_out = calls, tin, tout
        for s in res.steps:
            if s.status == "running":
                # stop não é erro de infraestrutura → skipped; outra interrupção → error
                s.status = "skipped" if res.status == "cancelled" else "error"
                s.reason = s.reason or ("Interrompido pelo stop." if res.status == "cancelled"
                                        else "Interrompido.")
            elif s.status == "pending":
                s.status = "skipped"
                s.reason = s.reason or ("Não executado (stop)." if res.status == "cancelled"
                                        else "Não executado.")
        for s in res.steps:
            if s.status != "skipped" and s.outcome is None:
                s.outcome = "inconclusive"  # ex.: interrompido
        res.outcomes = {k: n for k in ("verified", "executed", "inconclusive")
                        if (n := sum(s.outcome == k for s in res.steps))}
        res.finished_at = now_iso()
        res.duration_ms = int((time.perf_counter() - t0) * 1000)
        bad = next((s for s in res.steps if s.status in ("failed", "error")), None)
        if res.failure_category is None and bad is not None and res.status in ("failed", "error"):
            res.failure_category = bad.failure_category
        res.summary = _summary(res)
        res.progress.message = res.status
        for name in ("result.json", "qagent.log"):
            ex.add_artifact(name)
        log.write("execution_finished", status=res.status, summary=res.summary, ms=res.duration_ms)
        ex.save()


async def _connect_with_retries(ex: Execution, settings: Settings, caps: dict, udid: str | None
                                ) -> tuple[AsyncExitStack, McpConnection, AppiumSession]:
    """G3: liga ao appium-mcp e cria a sessão Appium; repete só esta preparação (infraestrutura, antes de
    qualquer passo) até options.infraRetries vezes. Devolve a pilha que fecha a ligação."""
    res, log, retries = ex.result, ex.log, ex.request.options.infra_retries
    for attempt in range(retries + 1):
        res.progress.message = "A criar a sessão Appium" + (f" (tentativa {attempt + 1})" if attempt else "")
        ex.save()
        stack = AsyncExitStack()
        try:
            conn = await stack.enter_async_context(McpConnection(settings, ex.run_dir))
            log.write("mcp_connected", mcpSessionId=conn.mcp_session_id, ms=conn.connect_ms)
            sess = AppiumSession(conn)
            t = time.perf_counter()
            await sess.create_android(caps, udid)
            log.write("appium_session_created", sessionId=sess.session_id, udid=sess.udid,
                      ms=int((time.perf_counter() - t) * 1000),
                      capabilities={k: v for k, v in caps.items() if k != "appium:app"})
            return stack, conn, sess
        except asyncio.CancelledError:
            await stack.aclose()
            raise
        except Exception as e:  # noqa: BLE001 — preparação = infraestrutura por definição
            try:
                await stack.aclose()
            except Exception:  # noqa: BLE001
                pass
            if attempt >= retries:
                raise
            res.metrics.infra_retries += 1
            log.write("infra_retry", attempt=attempt + 1, category=classify_exception(e),
                      error=log.mask(f"{type(e).__name__}: {str(e)[:300]}"))
            await asyncio.sleep(RETRY_DELAY_S * (attempt + 1))
    raise AssertionError("unreachable")


RETRY_DELAY_S = 3.0  # pausa base entre tentativas de preparação (G3)

_REAL_ACTIONS = ("tap", "long_press", "type_text", "swipe", "scroll", "open_app", "close_apps", "human_input",
                 "already_done", "key_")


def step_outcome(step: StructuredStep, sr: StepResult) -> str | None:
    """G3: força da evidência do veredicto (models.StepOutcome). Regra genérica, só sobre o que foi registado."""
    if sr.status == "skipped":
        return None
    if sr.status == "error":
        return "inconclusive"
    if step.action in ("assert_visible", "assert_text"):
        return "verified"
    if step.action == "manual":
        return "executed"
    if step.action != "ai":  # tap/type/scroll_to/back/wait: falha = elemento não encontrado (observado)
        return "verified" if sr.status == "failed" else "executed"
    checked = any((a.tool == "assert" and a.result in ("ok", "not_met"))
                  or (a.tool == "wait_for_text" and (a.result in ("visible", "gone") or a.result.startswith("timeout")))
                  for a in sr.actions)
    if checked:
        return "verified"
    if sr.status == "passed" and any(a.tool.startswith(_REAL_ACTIONS) and a.result == "ok" for a in sr.actions):
        return "executed"
    return "inconclusive"  # só o juízo do LLM sobre o ecrã


_SYSTEM_PKG_PREFIXES = ("android", "com.android.systemui", "com.android.permissioncontroller",
                        "com.google.android.permissioncontroller", "com.google.android.packageinstaller")
_PKG_RE = re.compile(r"[A-Za-z][\w]*(\.[A-Za-z_][\w]*)+")


async def _record_app_versions(ex: Execution, udid: str | None) -> None:
    """G3: versionName das apps do teste (pedido, resetApps e apps abertas/alcançadas durante a execução)."""
    if not udid:
        return
    req, res = ex.request, ex.result
    pkgs: list[str] = []
    if req.app and req.app.android and req.app.android.app_package:
        pkgs.append(req.app.android.app_package)
    pkgs += req.options.reset_apps
    pkgs += [a.selector for s in res.steps for a in s.actions if a.tool in ("open_app", "app_switched") and a.selector]
    home = res.device.home_package
    pkgs = [p for p in dict.fromkeys(pkgs) if _PKG_RE.fullmatch(p) and not p.startswith(_SYSTEM_PKG_PREFIXES)
            and p != home and (home or "launcher" not in p)]
    if not pkgs:
        return
    try:
        res.app_versions = await asyncio.wait_for(app_versions(udid, pkgs[:10]), timeout=30)
    except Exception as e:  # noqa: BLE001 — informativo, nunca muda o resultado
        ex.log.write("app_versions_error", error=str(e)[:200])


class RunState(TypedDict):
    index: int
    stop: bool


def build_graph(ex: Execution, sess: AppiumSession, executor: StructuredExecutor):
    """Grafo LangGraph (CPS 6.2/7.1): normalize → execute_step (ciclo) → fim.
    O ReAct do LLM fica DENTRO de execute_step (AiStepExecutor); a sessão Appium fica fora do grafo."""
    res, req, log = ex.result, ex.request, ex.log

    async def normalize(state: RunState) -> dict:
        if ex.steps or not req.test_execution:
            return {}
        res.progress.message = "A dividir o caso de teste em passos (LLM)"
        ex.save()
        try:
            case, steps, tokens = await from_free_text(req.test_execution, ex.llm, list(ex.test_data))
        except Exception as e:  # noqa: BLE001
            raise NormalizerError(f"normalizador (LLM): {type(e).__name__}: {str(e)[:300]}") from e
        ex.steps = steps
        ex.norm_calls, ex.norm_tokens = 1, tokens
        res.prompt_versions["normalizer"] = DEFAULT_NORMALIZER
        res.steps = [StepResult(id=i, name=s.name) for i, s in enumerate(steps, 1)]
        res.progress.total_steps = len(steps)
        log.write("normalized", name=case.name, steps=[s.name for s in steps], tokens=tokens)
        ex.save()
        return {}

    async def execute_step(state: RunState) -> dict:
        i = state["index"]
        step, sr = ex.steps[i], res.steps[i]
        if state["stop"]:
            sr.status, sr.reason = "skipped", "Não executado: passo anterior falhou (stopOnFailure)."
            return {"index": i + 1}
        n = i + 1
        sr.status = "running"
        res.progress.current_step = n
        res.progress.message = f"A executar o passo {n} de {len(ex.steps)}"
        ex.save()
        t = time.perf_counter()
        is_ai = step.action == "ai"
        # Passos LLM: chamadas + backoff de 429 → mínimo de 180 s.
        timeout = max(req.options.timeout_per_step_sec, 180) if is_ai else req.options.timeout_per_step_sec
        try:
            history = [(s.id, s.name, s.status, (s.reason or "")[:200]) for s in res.steps[:i]]
            instruction, human_rounds = step.text, 0
            while True:
                try:
                    if step.action == "manual":
                        if human_rounds:
                            sr.reason = "Ação manual concluída pelo utilizador."
                            break
                        raise HumanInputRequired(step.text)
                    coro = (ex.ai_exec.run_instruction(instruction, sr, history, tester_acted=human_rounds > 0)
                            if is_ai else executor.run(step, sr))
                    await asyncio.wait_for(coro, timeout=timeout)
                    break
                except HumanInputRequired as h:
                    human_rounds += 1
                    if human_rounds > 3:
                        raise RuntimeError("demasiados pedidos de intervenção do utilizador no mesmo passo")
                    waited = await _wait_for_human(ex, n, h.instruction)
                    sr.actions.append(ActionRecord(tool="human_input", selector=h.instruction,
                                                   result=f"done by user after {waited:.0f}s"))
                    instruction = (f"{step.text}\n(Note: the tester has just done this manually on the "
                                   f"device: \"{h.instruction}\". Continue the step from the current screen.)")
            sr.status = "passed"
        except StepFailed as e:
            sr.status, sr.reason, sr.failure_category = "failed", str(e), "app"
        except asyncio.TimeoutError:
            sr.status, sr.reason, sr.failure_category = "error", f"Timeout do passo ({timeout:g}s).", "environment"
        except ToolError as e:
            sr.status, sr.reason = "error", f"Erro do appium-mcp: {str(e)[:300]}"
            sr.failure_category = classify_exception(e)
        except (PreexistingState, HumanTimeout) as e:
            sr.status, sr.reason, sr.failure_category = "error", log.mask(str(e)), "environment"
        except Exception as e:  # noqa: BLE001 — ex.: erro/quota do provider LLM, limite de ações
            sr.status = "error"
            kind = " LLM" if is_ai else ""
            sr.reason = log.mask(f"Erro do executor{kind}: {type(e).__name__}: {str(e)[:300]}")
            sr.failure_category = "llm" if is_ai else classify_exception(e)
        await _evidence(ex, sess, n, sr)
        sr.outcome = step_outcome(step, sr)
        sr.duration_ms = int((time.perf_counter() - t) * 1000)
        log.write("step_finished", step=n, name=sr.name, status=sr.status, reason=sr.reason,
                  ms=sr.duration_ms, tokens=sr.tokens,
                  actions=[a.model_dump(by_alias=True) for a in sr.actions])
        ex.save()
        return {"index": n, "stop": sr.status != "passed" and req.options.stop_on_failure}

    def route(state: RunState) -> str:
        return "execute_step" if state["index"] < len(ex.steps) else END

    g = StateGraph(RunState)
    g.add_node("normalize", normalize)
    g.add_node("execute_step", execute_step)
    g.add_edge(START, "normalize")
    g.add_conditional_edges("normalize", route, ["execute_step", END])
    g.add_conditional_edges("execute_step", route, ["execute_step", END])
    return g.compile()


async def _wait_for_human(ex: Execution, step_no: int, instruction: str) -> float:
    """Pausa a execução até o QA carregar em Continuar (POST …/resume). Fora do timeout do passo."""
    res, log = ex.result, ex.log
    ex.human_event = asyncio.Event()
    res.status = "waiting_for_user"
    res.progress.awaiting_user = instruction
    res.progress.awaiting_since = now_iso()
    res.progress.message = f"Passo {step_no}: à espera do utilizador — {instruction}"
    ex.save()
    log.write("waiting_for_user", step=step_no, instruction=instruction)
    t0 = time.perf_counter()
    timeout = ex.request.options.human_timeout_sec
    try:
        await asyncio.wait_for(ex.human_event.wait(), timeout=timeout)
    except asyncio.TimeoutError as e:
        raise HumanTimeout(f"Sem resposta do utilizador em {timeout:g}s ({instruction})") from e
    finally:
        ex.human_event = None
        res.status = "running"
        res.progress.awaiting_user = res.progress.awaiting_since = None
        res.progress.message = f"A executar o passo {step_no} de {len(ex.steps)}"
        ex.save()
    waited = time.perf_counter() - t0
    log.write("user_resumed", step=step_no, waited_s=round(waited, 1))
    return waited


async def _evidence(ex: Execution, sess: AppiumSession, i: int, sr: StepResult) -> None:
    """Deteção de diálogo de sistema + screenshot/page source conforme options.screenshots."""
    opts = ex.request.options
    try:
        xml = await sess.page_source()
        if has_error_dialog(xml):
            # Só os diálogos de erro do Android (aerr_*). Notificações/dicas/permissões não são erro
            # (F-multi-app, 2026-11-12: o alarme de outra app em ecrã inteiro era tomado por ANR).
            sr.status, sr.failure_category = "error", "app"  # a app não responde / parou
            sr.reason = (f"{sr.reason + ' ' if sr.reason else ''}Diálogo de erro do Android em primeiro plano "
                         f"(app não responde ou parou).")
        if sr.status == "failed":
            texts = AppiumSession.visible_texts(xml)
            if texts:
                # Mascarar: um segredo escrito num campo não-password apareceria aqui (CA9).
                sr.reason = ex.log.mask(f"{sr.reason} Textos no ecrã: {texts}")
        if sr.status != "passed":
            name = f"step-{i:02d}.xml"
            # Mascarar: um segredo escrito num campo não-password fica em claro no XML (falha anterior
            # a 2026-11-13; o XML só era gravado em passos não passados, mas sem máscara).
            (ex.run_dir / name).write_text(ex.log.mask(xml), encoding="utf-8")
            sr.evidence.page_source = name
            ex.add_artifact(name)
    except Exception as e:  # noqa: BLE001 — evidência nunca deve mascarar o resultado do passo
        ex.log.write("evidence_error", step=i, kind="page_source", error=str(e)[:300])
    if opts.screenshots == "every_step" or (opts.screenshots == "on_failure" and sr.status != "passed"):
        try:
            src = await sess.screenshot()
            name = f"step-{i:02d}.png"
            shutil.copy2(src, ex.run_dir / name)  # SCREENSHOTS_DIR é global no servidor HTTP (F1 5.5)
            sr.evidence.screenshot = name
            ex.add_artifact(name)
        except Exception as e:  # noqa: BLE001
            ex.log.write("evidence_error", step=i, kind="screenshot", error=str(e)[:300])


async def _cleanup(ex: Execution, sess: AppiumSession) -> None:
    """Apaga a sessão Appium (também em stop/erro). Se falhar, o fecho da ligação MCP
    dispara APPIUM_MCP_ON_CLIENT_DISCONNECT=delete_all (F1-registo 5.2)."""
    sid = sess.session_id
    if not sid:
        return
    try:
        await asyncio.wait_for(sess.delete(), timeout=30)
        ex.log.write("appium_session_deleted", sessionId=sid)
    except BaseException as e:  # noqa: BLE001 — inclui CancelledError durante o stop
        ex.log.write("appium_session_delete_failed", sessionId=sid, error=repr(e)[:300])


def request_for_disk(req: TestExecutionInput) -> str:
    data = req.model_dump(by_alias=True, exclude_none=True)
    data["testData"] = {k: (v if _SECRET_REF_RE.match(v) else ("***" if _SENSITIVE_KEY_RE.search(k) else v))
                        for k, v in req.test_data.items()}
    return json.dumps(data, indent=2, ensure_ascii=False)
