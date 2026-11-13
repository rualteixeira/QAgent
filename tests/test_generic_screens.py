"""Ecrãs sintéticos e genéricos (package neutro, resolução de telemóvel real 1080x2400): o agente e o gerador de
scripts têm de funcionar com padrões de interface comuns, sem depender das apps usadas no desenvolvimento.

form   — campos de texto, interruptor, caixa de seleção, lista suspensa, botão
list   — 5 itens com o mesmo id e um botão flutuante por cima do último
dialog — diálogo por cima do conteúdo
canvas — superfície desenhada sem acessibilidade (só visível na captura) + um botão listado
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import qagent.ai_executor as ai_mod
from qagent.ai_executor import AiStepExecutor
from qagent.codegen import generate_python_script
from qagent.executor import StepFailed, StructuredExecutor
from qagent.llm import ScriptedChatModel
from qagent.models import ExecutionResult, StepResult
from qagent.screen import free_point, parse_screen, verify_assertion

DATA = Path(__file__).parent / "data" / "generic"
P = "com.example.app:id/"


def xml(name: str) -> str:
    return (DATA / f"{name}.xml").read_text(encoding="utf-8")


def png_header(w: int, h: int) -> bytes:
    """PNG mínimo (só o cabeçalho IHDR interessa ao QAgent para saber o tamanho da captura)."""
    return (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + w.to_bytes(4, "big") + h.to_bytes(4, "big")
            + b"\x08\x06\x00\x00\x00" + b"\x00" * 4)


class _Res:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeConn:
    def __init__(self, page: str, shot: Path | None = None) -> None:
        self.page, self.shot, self.calls = page, shot, []

    async def call(self, name, args=None, *, timeout_s=None):
        self.calls.append((name, dict(args or {})))
        if name == "appium_get_page_source":
            return _Res(f"Page source retrieved successfully: \n```xml {self.page}```")
        if name == "appium_find_element":
            return _Res("elementId 'el-1'")
        if name == "appium_screenshot":
            return _Res(f"Screenshot saved successfully to: {self.shot}")
        return _Res("ok")


def call(name: str, i: int, **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"c{i}"}])


def run(conn: FakeConn, script: list[AIMessage], instruction: str) -> tuple[StepResult, list[str]]:
    seen: list[str] = []
    orig = ToolMessage.__init__

    def spy(self, content, **kw):
        seen.append(str(content))
        orig(self, content, **kw)
    ToolMessage.__init__ = spy
    try:
        ex = AiStepExecutor(conn, "sid-1", StructuredExecutor(conn, "sid-1", {}), ScriptedChatModel(responses=script),
                            {}, secret_keys=set())
        sr = StepResult(id=1, name="x")
        try:
            asyncio.run(ex.run_instruction(instruction, sr))
        except StepFailed:
            pass  # veredicto 'failed' do passo: o que interessa aqui são as ações e as mensagens
    finally:
        ToolMessage.__init__ = orig
    return sr, seen


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_s):
        return None
    monkeypatch.setattr(ai_mod.asyncio, "sleep", instant)


# ---------- leitura do ecrã ----------

def test_form_controls_are_listed_with_state_and_stable_locators():
    s = parse_screen(xml("form"))
    by_rid = {e.rid: e for e in s.elements}
    assert by_rid[P + "input_name"].editable and by_rid[P + "input_note"].editable
    assert by_rid[P + "switch_option"].checkable and not by_rid[P + "switch_option"].checked
    assert by_rid[P + "check_terms"].checked
    assert "First choice" in by_rid[P + "choice"].inner_texts            # lista suspensa mostra a opção atual
    for rid in ("input_name", "switch_option", "choice", "btn_save"):
        e = by_rid[P + rid]
        assert e.locator.strategy == "id" and not e.fragile, rid           # ids únicos → locator estável


def test_list_items_can_be_counted_and_floating_button_does_not_hide_them():
    s = parse_screen(xml("list"))
    spec = {"kind": "count", "strategy": "id", "selector": P + "item", "op": "eq", "count": 5}
    assert verify_assertion(s, spec)[0]
    assert not verify_assertion(s, {**spec, "count": 4})[0]
    last = [e for e in s.elements if e.rid == P + "item"][-1]
    fab = next(e for e in s.elements if e.rid == P + "fab")
    clickables = [e.bounds for e in s.elements if e.clickable and e is not last]
    # O centro do último item não está tapado pelo botão (fica à direita) → toque normal.
    assert free_point(last.bounds, clickables) is None
    # Um alvo cujo centro fica debaixo do botão → ponto livre fora do botão.
    x, y = free_point((800, 1400, 1000, 1500), [fab.bounds])         # centro (900,1450) debaixo do botão
    assert not (860 <= x <= 1040 and 1360 <= y <= 1540)


def test_dialog_buttons_are_listed_together_with_the_content_behind():
    s = parse_screen(xml("dialog"))
    texts = s.texts()
    assert "Continue?" in texts and "OK" in texts and "Cancel" in texts and "Open" in texts
    ok = next(e for e in s.elements if e.text == "OK")
    assert (ok.locator.strategy, ok.locator.value) == ("id", "android:id/button1")


def test_drawn_surface_is_not_listed_and_description_points_to_the_screenshot():
    s = parse_screen(xml("canvas"))
    assert [e.rid for e in s.elements] == [P + "menu"]                  # a superfície desenhada não aparece


# ---------- agente: ações num ponto da captura ----------

def test_point_action_requires_a_screenshot_first(tmp_path):
    conn = FakeConn(xml("canvas"))
    sr, seen = run(conn, [call("tap_point", 1, x=10, y=10),
                          call("finish_step", 2, status="failed", reason="sem captura")], "[WHEN] toca no centro")
    assert any("call look_at_screen first" in m for m in seen)
    assert not any(n == "appium_gesture" for n, _ in conn.calls)


def test_point_action_converts_screenshot_pixels_to_screen_and_records_the_surface(tmp_path):
    shot = tmp_path / "s.png"
    shot.write_bytes(png_header(400, 889))                             # captura reduzida (maxWidth 400)
    conn = FakeConn(xml("canvas"), shot)
    sr, _ = run(conn, [call("look_at_screen", 1), call("tap_point", 2, x=200, y=444),
                       call("finish_step", 3, status="passed", reason="tocado")], "[WHEN] toca no centro")
    taps = [a for n, a in conn.calls if n == "appium_gesture"]
    assert taps == [{"action": "tap", "x": 540, "y": 1199, "sessionId": "sid-1"}]   # 200*1080/400, 444*2400/889
    rec = [a for a in sr.actions if a.tool == "tap"][0]
    assert rec.strategy == "coordinates" and rec.selector == "540,1199"
    assert rec.target.cls == "android.view.View" and rec.target.bounds == [0, 160, 1080, 2400]
    # O script gerado repete o toque só se a mesma superfície estiver nesse sítio.
    result = ExecutionResult(execution_id="x", record_id="x", created_at="2026-11-13T00:00:00Z", status="passed",
                             steps=[StepResult(id=1, name="When toca", status="passed", actions=sr.actions,
                                               locators=sr.locators)])
    code = generate_python_script(result, {"testExecution": "t", "platform": "android"})
    compile(code, "t.py", "exec")
    assert "tap_xy(540, 1199, expect={'cls': 'android.view.View', 'bounds': (0, 160, 1080, 2400)})" in code


def test_point_on_a_listed_control_is_redirected_to_its_ref(tmp_path):
    shot = tmp_path / "s.png"
    shot.write_bytes(png_header(1080, 2400))
    conn = FakeConn(xml("canvas"), shot)
    sr, seen = run(conn, [call("look_at_screen", 1), call("tap_point", 2, x=80, y=80),
                          call("finish_step", 3, status="failed", reason="x")], "[WHEN] abre o menu")
    assert any("inside listed element e1" in m and "ref=e1" in m for m in seen)
    assert not any(n == "appium_gesture" for n, _ in conn.calls)


def test_point_outside_the_screenshot_is_rejected(tmp_path):
    shot = tmp_path / "s.png"
    shot.write_bytes(png_header(400, 889))
    conn = FakeConn(xml("canvas"), shot)
    _, seen = run(conn, [call("look_at_screen", 1), call("tap_point", 2, x=500, y=10),
                         call("finish_step", 3, status="failed", reason="x")], "[WHEN] toca")
    assert any("outside the screenshot (400x889 px)" in m for m in seen)


def test_dialog_button_is_tapped_by_ref_with_its_stable_locator():
    conn = FakeConn(xml("dialog"))
    s = parse_screen(xml("dialog"))
    ok = next(e for e in s.elements if e.text == "OK")
    sr, _ = run(conn, [call("tap", 1, ref=ok.ref), call("finish_step", 2, status="passed", reason="confirmado")],
                "[WHEN] confirma o diálogo")
    tap = [a for a in sr.actions if a.tool == "tap"][0]
    assert (tap.strategy, tap.selector) == ("id", "android:id/button1")
