"""Verificações estruturadas (THEN): confirmação determinística num ecrã real e geração de asserts."""

import json
from pathlib import Path

from qagent.codegen import generate_python_script
from qagent.models import ActionRecord, ExecutionResult, StepResult
from qagent.screen import parse_screen, verify_assertion

SCREEN = parse_screen((Path(__file__).parent / "data" / "login_error_screen.xml").read_text(encoding="utf-8"))
ERR_ID = "com.saucelabs.mydemoapp.android:id/passwordErrorTV"


def test_visible_and_absent_by_text():
    assert verify_assertion(SCREEN, {"kind": "visible", "text": "locked out"})[0]
    assert verify_assertion(SCREEN, {"kind": "absent", "text": "Products"})[0]
    assert not verify_assertion(SCREEN, {"kind": "absent", "text": "LOCKED OUT"})[0]  # case-insensitive


def test_text_equals_and_contains_by_locator():
    spec = {"kind": "text_equals", "strategy": "id", "selector": ERR_ID, "text": "Sorry this user has been locked out."}
    assert verify_assertion(SCREEN, spec)[0]
    ok, observed = verify_assertion(SCREEN, {**spec, "text": "Welcome"})
    assert not ok and "locked out" in observed
    assert verify_assertion(SCREEN, {**spec, "kind": "text_contains", "text": "locked"})[0]


def test_count():
    nid = "com.saucelabs.mydemoapp.android:id/nameET"
    assert verify_assertion(SCREEN, {"kind": "count", "strategy": "id", "selector": nid, "op": "eq", "count": 1})[0]
    assert not verify_assertion(SCREEN, {"kind": "count", "strategy": "id", "selector": nid, "op": "eq", "count": 2})[0]
    assert verify_assertion(SCREEN, {"kind": "count", "strategy": "id", "selector": nid, "op": "ge", "count": 1})[0]


def test_codegen_emits_asserts():
    specs = [{"kind": "count", "strategy": "id", "selector": "pkg:id/row", "op": "eq", "count": 2},
             {"kind": "text_equals", "strategy": "id", "selector": ERR_ID, "text": "Sorry"},
             {"kind": "absent", "text": "Erro"}]
    acts = [ActionRecord(tool="assert", strategy=s.get("strategy"), selector=s.get("selector"), result="ok",
                         value=json.dumps(s)) for s in specs]
    res = ExecutionResult(execution_id="a1", record_id="a1", created_at="2026-11-13T00:00:00Z", status="passed",
                          steps=[StepResult(id=1, name="Then carrinho com 2 produtos", status="passed", actions=acts)])
    code = generate_python_script(res, {"testExecution": "x"})
    compile(code, "t.py", "exec")
    assert "assert_count(AppiumBy.ID, 'pkg:id/row', 'eq', 2)" in code
    assert f"assert_text(AppiumBy.ID, '{ERR_ID}', 'Sorry')" in code
    assert "wait_text('Erro', gone=True, timeout=10)" in code


def test_free_point_avoids_a_floating_button_over_the_target():
    # Centro de um texto (240,492) debaixo de um botão flutuante [236,476][292,532].
    from qagent.screen import free_point
    target, card, fab = (213, 483, 268, 501), (160, 300, 320, 560), (236, 476, 292, 532)
    x, y = free_point(target, [card, fab])
    assert 213 <= x <= 268 and 483 <= y <= 501 and not (236 <= x <= 292 and 476 <= y <= 532)
    assert free_point(target, [card]) is None                       # só o cartão que o contém: centro livre
    assert free_point((0, 0, 10, 10), [(0, 0, 9, 9)]) is None                  # algo DENTRO do alvo: não tapa
    assert free_point((0, 0, 10, 10), [(4, 4, 20, 6)]) == (2, 5)            # barra sobre o centro → ponto livre
    assert free_point((236, 476, 292, 532), [(200, 400, 300, 600)]) is None   # contido noutro: não é tapado
