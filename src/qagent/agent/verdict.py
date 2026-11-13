"""Regras do veredicto de um passo (finish_step) e verificações estruturadas. As regras críticas são validadas
aqui, no código, e não só no prompt."""

from __future__ import annotations

import json

from qagent.agent.device import Device
from qagent.agent.errors import PreexistingState, ToolMisuse
from qagent.agent.schemas import Assertion, FinishArgs
from qagent.agent.state import StepState
from qagent.models import ActionRecord, StepResult
from qagent.screen import verify_assertion


def assertion_spec(a: Assertion, device: Device) -> dict:
    """ref → locator estável (as refs mudam a cada ecrã; o locator não). Lança ToolMisuse se inválida."""
    spec: dict = {"kind": a.kind}
    if a.kind in ("text_equals", "text_contains", "absent") and not a.text:
        raise ToolMisuse(f"assertion {a.kind} needs `text`")
    if a.kind == "count" and a.count is None:
        raise ToolMisuse("assertion count needs `count`")
    if a.ref:
        el = device.element(a.ref)
        if a.kind == "count":
            if not el.rid:
                raise ToolMisuse("count needs a ref whose element has an id (id=…); pick an item that has one")
            spec.update(strategy="id", selector=el.rid)
        else:
            if not el.locator or el.locator.strategy not in ("accessibility id", "id", "-android uiautomator"):
                raise ToolMisuse("that element has no stable locator; use kind=visible/absent with `text`")
            spec.update(strategy=el.locator.strategy, selector=el.locator.value)
    elif a.kind in ("text_equals", "text_contains", "count"):
        raise ToolMisuse(f"assertion {a.kind} needs `ref`")
    elif not a.text:
        raise ToolMisuse("assertion visible needs `ref` or `text`")
    if a.text is not None:
        spec["text"] = a.text
    if a.kind == "count":
        spec.update(op=a.op, count=a.count)
    return spec


def _assert_record(spec: dict, outcome: str) -> ActionRecord:
    return ActionRecord(tool="assert", strategy=spec.get("strategy"), selector=spec.get("selector"),
                        result=outcome, value=json.dumps(spec, ensure_ascii=False))


class VerdictJudge:
    def __init__(self, device: Device, state: StepState, result: StepResult) -> None:
        self.d, self.st, self.result = device, state, result

    async def confirm_assertion(self, a: Assertion | None) -> str | None:
        """None se confirmada num ecrã relido (e regista-a); senão a mensagem de rejeição para o LLM."""
        if a is None:
            return ("Rejected: a passed [THEN] step needs `assertion` (machine-checkable). Add it, or finish "
                    "failed if the expected result does not hold.")
        try:
            spec = assertion_spec(a, self.d)
        except ToolMisuse as e:
            return f"Rejected: invalid assertion — {e}"
        ok, observed = verify_assertion(await self.d.read_screen(), spec)
        if not ok:
            return (f"Rejected: the assertion was NOT confirmed on a fresh screen ({observed}). Re-check (refs may "
                    f"have changed: use the latest screen) or finish failed.\nScreen now:\n{self.d.describe()}")
        self.result.actions.append(_assert_record(spec, "ok"))
        return None

    async def validate(self, verdict: FinishArgs, history: list, tester_acted: bool) -> str | None:
        """Regras do veredicto, por esta ordem (G1, 2026-11-13: a regra genérica 'nada feito' avaliada primeiro
        anulava as específicas — um THEN com asserção correta ou um WHEN com how declarado eram recusados).
        Devolve a mensagem de rejeição para o LLM, None se aceite; PreexistingState → erro de ambiente."""
        st, result = self.st, self.result
        if (verdict.status == "failed" and st.is_when and st.action_successes > 0
                and st.action_failures == 0 and not st.when_fail_challenged):
            # G1 (2026-11-13, CA3): o modelo falhou um WHEN cujas ações correram todas bem por julgar o resultado
            # de negócio (isso é do THEN seguinte). Contestar UMA vez; se insistir, aceita-se (pode haver motivo).
            st.when_fail_challenged = True
            return ("Check: this is an action step ([WHEN]) and all its actions succeeded. Judge only whether the "
                    "action could be performed; whatever the screen shows afterwards (including any message) is "
                    "verified by the following [THEN] step. Finish passed (how=performed) unless the action itself "
                    "could not be performed — if so, finish failed again explaining why.")
        if verdict.status == "failed":
            return await self._validate_failed_then(verdict) if st.is_then else None
        if st.is_then:  # verificação estruturada obrigatória; confirmada num ecrã relido = observação
            return await self.confirm_assertion(verdict.assertion)
        if st.is_when:  # o modelo declara `how`; o código valida
            return self._validate_when_how(verdict, history, tester_acted)
        if st.successes == 0:  # passo sem tipo Gherkin
            return ("Rejected: nothing was done or observed yet. Perform the action or verify explicitly "
                    "(wait_for_text/read_text) first.")
        return None

    async def _validate_failed_then(self, verdict: FinishArgs) -> str | None:
        st = self.st
        if verdict.assertion is None:
            if st.then_fail_challenged:
                return None
            # G3: sem a asserção esperada a falha fica só no juízo do LLM (outcome inconclusive) e o script
            # gerado não a reproduz. Pedir UMA vez; se o modelo insistir sem ela, aceita-se.
            st.then_fail_challenged = True
            return ("Check: add `assertion` = the machine-checkable check of what was EXPECTED (e.g. visible with "
                    "the expected text). It is re-checked on a fresh screen and must NOT hold; then finish failed "
                    "again with the same reason.")
        try:  # registar o que era esperado (o script gerado reproduz a asserção)
            spec = assertion_spec(verdict.assertion, self.d)
        except ToolMisuse:
            return None
        # G3: confirmar a falha num ecrã relido. Se o esperado afinal se verifica, o veredicto contradiz o
        # ecrã → contestar UMA vez. "not_met" = falha verificada pela máquina (outcome verified).
        ok, observed = verify_assertion(await self.d.read_screen(), spec)
        if ok and not st.then_fail_challenged:
            st.then_fail_challenged = True
            return (f"Check: you finished failed, but your own expected assertion HOLDS on a fresh screen "
                    f"({observed}). Re-check: finish passed with that assertion if the expected result is "
                    f"met, or finish failed again with an assertion that is really not met.")
        self.result.actions.append(_assert_record(spec, "expected" if ok else "not_met"))
        return None

    def _validate_when_how(self, verdict: FinishArgs, history: list, tester_acted: bool) -> str | None:
        if verdict.how == "already_true_before_test" and not self.st.preexisting_challenged:
            # O modelo pode tomar dados já existentes (contadores, registos, app já aberta) como "a ação já estava
            # feita" e não agir. Contestar UMA vez; se insistir, aceita-se e é erro de ambiente (ex.: criar um
            # registo único que já existe).
            self.st.preexisting_challenged = True
            return ("Check: this action step asks you to DO something now. Data that already exists (items, "
                    "records, counters, an app already open) does not mean this test performed the action, and it "
                    "does not stop you from performing it again. Perform the action now and finish with "
                    "how=performed. Use already_true_before_test only if the action is impossible because its "
                    "result already exists and cannot be created again — then finish with it again.")
        if verdict.how == "already_true_before_test":
            self.result.reason = verdict.reason
            raise PreexistingState(
                f"Estado pré-existente: {verdict.reason} — o ambiente não estava limpo; "
                "a ação não foi executada por este teste (use options.resetApps).")
        if verdict.how == "done_by_tester":
            if not tester_acted:
                return ("Rejected: the tester did not act in this step (no request_human was completed). "
                        "Declare how honestly.")
            verdict.reason = f"{verdict.reason} (ação feita pelo tester)"
            return None
        if verdict.how == "already_done_by_step":
            done_by = verdict.already_done_by_step
            if not any(n == done_by and st == "passed" for n, _, st, _ in history):
                return f"Rejected: step {done_by} is not an earlier PASSED step of this test."
            verdict.reason = f"{verdict.reason} (ação já feita no passo {done_by})"
            self.result.actions.append(ActionRecord(tool="already_done", selector=f"step {done_by}", result="ok"))
            return None
        if self.st.action_successes == 0:
            return ("Rejected: how=performed but no action succeeded in this step. Perform the action, or "
                    "declare how honestly.")
        return None
