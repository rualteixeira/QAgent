"""G1 — ciclo do executor LLM (AiStepExecutor) com appium-mcp e LLM simulados.

Cobre as regras críticas de veredicto: ação real nos WHEN, `how` declarado, verificação estruturada nos THEN,
orçamento de ações, repetições, pedido de intervenção humana e segredos. Ecrã: XML real gravado (login com erro):
e10 = campo nameET, e12 = passwordET, e13 = mensagem de erro, e14 = botão Login.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import qagent.ai_executor as ai_mod
from qagent.ai_executor import AiStepExecutor, HumanInputRequired, PreexistingState
from qagent.executor import StepFailed, StructuredExecutor
from qagent.llm import ScriptedChatModel
from qagent.mcp_client import ToolError
from qagent.models import StepResult

XML = (Path(__file__).parent / "data" / "login_error_screen.xml").read_text(encoding="utf-8")
ERROR_TEXT = "Sorry this user has been locked out."


class _Res:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeConn:
    """Imita o McpConnection: responde às ferramentas do appium-mcp sem dispositivo."""

    def __init__(self, xml: str = XML, fail: set[str] | None = None) -> None:
        self.xml, self.fail, self.calls = xml, fail or set(), []

    async def call(self, name: str, args: dict | None = None, *, timeout_s: float | None = None) -> _Res:
        self.calls.append((name, dict(args or {})))
        if name in self.fail:
            raise ToolError(f"{name}: falha simulada")
        if name == "appium_get_page_source":
            return _Res(f"Page source retrieved successfully: \n```xml {self.xml}```")
        if name == "appium_find_element":
            return _Res("elementId 'el-1'\nSuccessfully found element")
        if name == "appium_screenshot":
            return _Res("Screenshot saved successfully to: C:\\tmp\\s.png")
        return _Res("ok")


class _Msgs:
    """Guarda as mensagens que o LLM recebeu (para verificar rejeições)."""


def call(name: str, i: int, **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"c{i}"}])


def make(script: list[AIMessage], conn: FakeConn | None = None, **kw) -> tuple[AiStepExecutor, FakeConn, ScriptedChatModel]:
    conn = conn or FakeConn()
    data = kw.pop("test_data", {"user": "bod@example.com", "password": "s3cr3t-pw"})
    llm = ScriptedChatModel(responses=script)
    ex = AiStepExecutor(conn, "sid-1", StructuredExecutor(conn, "sid-1", data), llm, data,
                        secret_keys={"password"}, **kw)
    return ex, conn, llm


def run(ex: AiStepExecutor, instruction: str, history=None) -> StepResult:
    sr = StepResult(id=1, name="x")
    asyncio.run(ex.run_instruction(instruction, sr, history))
    return sr


HOME = "com.vendor.home"  # ecrã inicial do dispositivo simulado (nome sem "launcher": genérico)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_s):
        return None
    monkeypatch.setattr(ai_mod.asyncio, "sleep", instant)

    async def fake_home(_udid):
        return HOME
    import qagent.agent.navigation as nav_mod
    monkeypatch.setattr(nav_mod, "home_package", fake_home)


# ---------- WHEN ----------

def test_when_with_real_action_passes_and_records_stable_locator():
    ex, conn, _ = make([call("tap", 1, ref="e14"),
                        call("finish_step", 2, status="passed", reason="Login tocado.")])
    sr = run(ex, "[WHEN] toca em Login")
    assert sr.reason == "Login tocado."
    tap = [a for a in sr.actions if a.tool == "tap"][0]
    assert (tap.strategy, tap.selector) == ("accessibility id", "Tap to login with given credentials")
    assert ("appium_gesture", {"action": "tap", "elementUUID": "el-1", "sessionId": "sid-1"}) in conn.calls


def test_when_without_action_is_rejected_then_accepted_after_acting():
    ex, _, _ = make([call("finish_step", 1, status="passed", reason="já está"),
                     call("tap", 2, ref="e14"),
                     call("finish_step", 3, status="passed", reason="feito")])
    sr = run(ex, "[WHEN] toca em Login")
    assert sr.reason == "feito"  # o 1.º 'passed' sem ação foi recusado


def test_when_preexisting_state_is_an_environment_error_if_model_insists():
    ex, _, _ = make([call("finish_step", 1, status="passed", reason="o registo já existe",
                          how="already_true_before_test"),
                     call("finish_step", 2, status="passed", reason="o registo único já existe; não pode ser criado",
                          how="already_true_before_test")])
    with pytest.raises(PreexistingState):
        run(ex, "[WHEN] cria o registo")


def test_when_preexisting_state_is_challenged_and_model_performs_the_action():
    # "Adiciona dois itens" com um contador já em 2: o modelo não pode dar a ação como feita sem agir.
    ex, _, _ = make([call("finish_step", 1, status="passed", reason="o contador já mostra 2",
                          how="already_true_before_test"),
                     call("tap", 2, ref="e14"),
                     call("finish_step", 3, status="passed", reason="item adicionado", how="performed")])
    sr = run(ex, "[WHEN] adiciona dois itens")
    assert sr.reason == "item adicionado" and any(a.tool == "tap" for a in sr.actions)


def test_when_already_done_by_step_is_validated_against_history():
    history = [(1, "When faz login", "passed", "ok")]
    ex, _, _ = make([call("finish_step", 1, status="passed", reason="feito no passo 9", how="already_done_by_step",
                          already_done_by_step=9),
                     call("finish_step", 2, status="passed", reason="feito no passo 1", how="already_done_by_step",
                          already_done_by_step=1)])
    sr = run(ex, "[WHEN] introduz a password", history)
    assert "passo 1" in sr.reason
    assert any(a.tool == "already_done" for a in sr.actions)


# ---------- THEN ----------

def test_then_passed_requires_assertion_and_it_is_reverified():
    ex, _, _ = make([call("finish_step", 1, status="passed", reason="erro visível"),  # sem assertion → recusado
                     call("finish_step", 2, status="passed", reason="erro visível",
                          assertion={"kind": "text_equals", "ref": "e13", "text": "Welcome"}),  # falsa → recusada
                     call("finish_step", 3, status="passed", reason="erro visível",
                          assertion={"kind": "text_equals", "ref": "e13", "text": ERROR_TEXT})])
    sr = run(ex, "[THEN] aparece a mensagem de utilizador bloqueado")
    asserts = [a for a in sr.actions if a.tool == "assert"]
    assert len(asserts) == 1 and asserts[0].result == "ok" and ERROR_TEXT in asserts[0].value


def test_then_failed_records_expected_assertion_and_raises():
    ex, _, _ = make([call("finish_step", 1, status="failed", reason="não aparece o catálogo",
                          assertion={"kind": "visible", "text": "Products"})])
    with pytest.raises(StepFailed):
        run(ex, "[THEN] é apresentado o catálogo")


# ---------- orçamento, repetições, humano, segredos ----------

def test_budget_exhausted_forces_a_verdict_instead_of_error():
    ex, _, _ = make([call("tap", 1, ref="e2"), call("tap", 2, ref="e3"), call("tap", 3, ref="e14"),
                     call("finish_step", 4, status="failed", reason="não encontrei o carrinho")], max_actions=2)
    with pytest.raises(StepFailed, match="carrinho"):
        run(ex, "[THEN] verifica o carrinho")


def test_exact_call_repeated_three_times_is_rejected(monkeypatch):
    seen: list[str] = []
    orig = ToolMessage.__init__

    def spy(self, content, **kw):
        seen.append(str(content))
        orig(self, content, **kw)
    monkeypatch.setattr(ToolMessage, "__init__", spy)
    ex, _, _ = make([call("read_text", 1, ref="e13"), call("read_text", 2, ref="e13"), call("read_text", 3, ref="e13"),
                     call("finish_step", 4, status="failed", reason="x")])
    with pytest.raises(StepFailed):
        run(ex, "[WHEN] lê")
    assert any("already made this exact call twice" in s for s in seen)


def test_request_human_interrupts_the_step():
    ex, _, _ = make([call("request_human", 1, instruction="Faz login no dispositivo")])
    with pytest.raises(HumanInputRequired, match="Faz login"):
        run(ex, "[WHEN] faz login")


def test_secret_typed_but_never_exposed():
    ex, conn, _ = make([call("type_text", 1, ref="e12", text="{{testData.password}}"),
                        call("finish_step", 2, status="passed", reason="password escrita")])
    sr = run(ex, "[WHEN] escreve a password")
    sent = [a for n, a in conn.calls if n == "appium_set_value"]
    assert sent and sent[0]["text"] == "s3cr3t-pw"            # o valor real vai para o dispositivo
    typed = [a for a in sr.actions if a.tool == "type_text"][0]
    assert typed.value == "{{testData.password}}"              # no registo fica só o template
    assert "s3cr3t-pw" not in sr.model_dump_json()


def test_unknown_ref_returns_error_to_llm_without_failing_the_step():
    ex, _, _ = make([call("tap", 1, ref="e999"), call("tap", 2, ref="e14"),
                     call("finish_step", 3, status="passed", reason="ok")])
    assert run(ex, "[WHEN] toca").reason == "ok"


def test_tool_error_from_appium_is_reported_not_crashing():
    ex, _, _ = make([call("tap", 1, ref="e14"), call("finish_step", 2, status="failed", reason="tap falhou")],
                    conn=FakeConn(fail={"appium_gesture"}))
    with pytest.raises(StepFailed, match="tap falhou"):
        run(ex, "[WHEN] toca")


def test_when_failed_after_successful_actions_is_challenged_once():
    # CA3: o modelo falhou o WHEN por ver a mensagem de erro; é contestado e passa (o THEN é que verifica).
    ex, _, _ = make([call("tap", 1, ref="e14"),
                     call("finish_step", 2, status="failed", reason="apareceu erro de bloqueio"),
                     call("finish_step", 3, status="passed", reason="Login tocado.")])
    assert run(ex, "[WHEN] faz login").reason == "Login tocado."


def test_when_failed_is_accepted_if_model_insists():
    ex, _, _ = make([call("tap", 1, ref="e14"),
                     call("finish_step", 2, status="failed", reason="a"),
                     call("finish_step", 3, status="failed", reason="o botão não reagiu")])
    with pytest.raises(StepFailed, match="não reagiu"):
        run(ex, "[WHEN] faz login")


def test_when_failed_with_failed_action_is_not_challenged():
    ex, _, _ = make([call("tap", 1, ref="e14"), call("finish_step", 2, status="failed", reason="tap falhou")],
                    conn=FakeConn(fail={"appium_gesture"}))
    with pytest.raises(StepFailed, match="tap falhou"):
        run(ex, "[WHEN] toca")


def test_then_failed_but_expected_assertion_holds_is_challenged_once():
    # G3: o modelo diz que falhou, mas a sua própria asserção esperada verifica-se no ecrã relido.
    ex, _, _ = make([call("finish_step", 1, status="failed", reason="não aparece o erro",
                          assertion={"kind": "text_equals", "ref": "e13", "text": ERROR_TEXT}),
                     call("finish_step", 2, status="passed", reason="o erro aparece",
                          assertion={"kind": "text_equals", "ref": "e13", "text": ERROR_TEXT})])
    sr = run(ex, "[THEN] aparece a mensagem de utilizador bloqueado")
    assert sr.reason == "o erro aparece"


def test_then_failed_with_unmet_assertion_is_recorded_as_not_met():
    ex, _, _ = make([call("finish_step", 1, status="failed", reason="não aparece o catálogo",
                          assertion={"kind": "visible", "text": "Products"})])
    sr = StepResult(id=1, name="x")
    with pytest.raises(StepFailed):
        asyncio.run(ex.run_instruction("[THEN] é apresentado o catálogo", sr))
    assert [a.result for a in sr.actions if a.tool == "assert"] == ["not_met"]


def test_then_failed_without_assertion_is_asked_once_for_the_expected_check():
    ex, _, _ = make([call("finish_step", 1, status="failed", reason="não aparece o catálogo"),
                     call("finish_step", 2, status="failed", reason="não aparece o catálogo",
                          assertion={"kind": "visible", "text": "Products"})])
    sr = StepResult(id=1, name="x")
    with pytest.raises(StepFailed):
        asyncio.run(ex.run_instruction("[THEN] é apresentado o catálogo", sr))
    assert [a.result for a in sr.actions if a.tool == "assert"] == ["not_met"]


def test_then_failed_without_assertion_accepted_if_model_insists():
    ex, _, _ = make([call("finish_step", 1, status="failed", reason="a"),
                     call("finish_step", 2, status="failed", reason="ecrã inesperado")])
    with pytest.raises(StepFailed, match="inesperado"):
        run(ex, "[THEN] é apresentado o catálogo")


def test_close_apps_without_list_closes_apps_of_the_test_and_goes_home():
    # "Fecha todas as apps" tem ferramenta própria (não é pedido ao QA).
    ex, conn, _ = make([call("close_apps", 1),
                        call("finish_step", 2, status="passed", reason="apps fechadas")])
    sr = run(ex, "[WHEN] fecha todas as apps")
    closed = [a["id"] for n, a in conn.calls if n == "appium_app_lifecycle" and a.get("action") == "terminate"]
    assert closed and all("launcher" not in p and p != "com.android.systemui" for p in closed)
    assert ("appium_mobile_press_key", {"keyCode": 3, "sessionId": "sid-1"}) in conn.calls   # ecrã inicial
    rec = [a for a in sr.actions if a.tool == "close_apps"][0]
    assert rec.selector == ",".join(closed) and sr.reason == "apps fechadas"


def test_close_apps_with_explicit_packages():
    ex, conn, _ = make([call("close_apps", 1, packages=["com.example.a", "com.example.b"]),
                        call("finish_step", 2, status="passed", reason="ok")])
    run(ex, "[WHEN] fecha as apps A e B")
    closed = [a["id"] for n, a in conn.calls if n == "appium_app_lifecycle" and a.get("action") == "terminate"]
    assert closed == ["com.example.a", "com.example.b"]


def test_close_apps_never_closes_the_device_home_app_whatever_its_name(monkeypatch):
    # O ecrã inicial é perguntado ao Android (não adivinhado pelo nome): aqui chama-se com.vendor.home.
    ex, conn, _ = make([call("close_apps", 1), call("finish_step", 2, status="passed", reason="ok")])
    ex._nav.opened.update({HOME, "com.example.homebanking"})
    run(ex, "[WHEN] fecha todas as apps")
    closed = [a["id"] for n, a in conn.calls if n == "appium_app_lifecycle" and a.get("action") == "terminate"]
    assert HOME not in closed and "com.example.homebanking" in closed
