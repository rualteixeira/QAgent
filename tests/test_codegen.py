"""Gerador de script Python + Appium (sem LLM): compila, reproduz as ações e não contém segredos."""

from qagent.codegen import generate_python_script
from qagent.models import ActionRecord, ExecutionResult, LocatorRecord, StepResult


def _result(status="passed"):
    s1 = StepResult(id=1, name="When Abre a app de contactos", status="passed",
                    actions=[ActionRecord(tool="list_apps", result="24 apps"),
                             ActionRecord(tool="open_app", selector="com.google.android.contacts", result="ok")])
    s2 = StepResult(id=2, name="When Cria um contacto", status="passed", actions=[
        ActionRecord(tool="tap", strategy="accessibility id", selector="Create contact", result="ok"),
        ActionRecord(tool="type_text", strategy="-android uiautomator", selector='new UiSelector().text("First name")',
                     result="ok", value="{{testData.name}}"),
        ActionRecord(tool="type_text", strategy="id", selector="pkg:id/password", result="ok",
                     value="{{testData.password}}"),
        ActionRecord(tool="key_enter", result="ok"),
        ActionRecord(tool="tap", strategy="coordinates", selector="160,600", result="ok"),
        ActionRecord(tool="scroll_down", result="ok"),
        ActionRecord(tool="human_input", selector="Faz login no dispositivo", result="done by user after 9s"),
    ], locators=[LocatorRecord(strategy="coordinates", value="160,600", fragile=True)])
    s3 = StepResult(id=3, name="Then O contacto aparece", status=status, reason="não apareceu", actions=[
        ActionRecord(tool="wait_for_text", selector="Multi App", result="visible", value="10"),
        ActionRecord(tool="read_text", strategy="id", selector="pkg:id/title", result="ok", value="Multi App"),
        ActionRecord(tool="read_text", strategy="id", selector="pkg:id/count", result="ok", value="2 items"),
    ])
    return ExecutionResult(execution_id="abc123", record_id="abc123", created_at="2026-11-12T00:00:00Z",
                           status=status, steps=[s1, s2, s3])


REQUEST = {"testExecution": "teste", "platform": "android",
           "testData": {"name": "Multi App", "password": "{{secret:demo_pass}}", "pin": "***"},
           "options": {"resetApps": ["com.google.android.contacts"]}}


def test_script_compiles_and_maps_actions():
    code = generate_python_script(_result(), REQUEST)
    compile(code, "test_abc123.py", "exec")
    assert "open_app('com.google.android.contacts', restart=False)" in code
    assert "tap(AppiumBy.ACCESSIBILITY_ID, 'Create contact')" in code
    assert "render('{{testData.name}}')" in code
    assert "driver.press_keycode(66)" in code
    assert "tap_xy(160, 600)" in code and "⚠ locator frágil" in code
    assert "manual_step('Faz login no dispositivo')" in code
    assert "wait_text('Multi App', gone=False, timeout=10)" in code
    assert "assert_text(AppiumBy.ID, 'pkg:id/title', 'Multi App')" in code
    assert "list_apps" not in code.split("def run_test")[1]
    assert "'mobile: clearApp'" in code and "com.google.android.contacts" in code


def test_secrets_become_env_vars():
    code = generate_python_script(_result(), REQUEST)
    assert "os.environ['QAGENT_SECRET_DEMO_PASS']" in code
    assert "os.environ['TESTDATA_PIN']" in code
    assert "10203040" not in code


def test_failed_execution_reproduces_failure():
    code = generate_python_script(_result(status="failed"), REQUEST)
    compile(code, "x.py", "exec")
    assert "raise AssertionError('Passo 3 failed na execução original: não apareceu')" in code
    assert "NÃO passou" in code


def test_wait_text_regex_has_no_backslashes_and_matches():
    # O parser de UiSelector do Appium não interpreta '\': um regex com barras invertidas nunca encontrava
    # textos com '.', '(' ou '$' (validado no emulador).
    import re
    code = generate_python_script(_result(), REQUEST)
    src = code[code.index("def text_regex"):code.index("def wait_text")]
    ns: dict = {}
    exec(src, ns)
    for text in (".NET BOT BLACK SWEATSHIRT", "Total: $19.500 (M)?", 'Diz "olá" [x]', "a\b ^ & c"):
        pat = ns["text_regex"](text)
        assert "\\" not in pat and '"' not in pat, pat
        assert re.fullmatch(pat.replace("(?isu)", "(?is)"), f"xx {text} yy"), (text, pat)


# ---------- toques por coordenadas: confirmar o elemento antes de tocar ----------

_PAGE = ('<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][320,640]">'
         '<node class="android.view.ViewGroup" text="" content-desc="" bounds="[0,460][160,560]"/>'
         '<node class="android.widget.Button" text="" content-desc="" bounds="[236,476][292,532]"/>'
         '</node></hierarchy>')


class _FakeDriver:
    def __init__(self, page):
        self.page_source = page


def _check_target_ns(page):
    import re
    import time
    import xml.etree.ElementTree as ET
    code = generate_python_script(_result(), REQUEST)
    src = code[code.index("def _bounds"):code.index("def tap_xy")]
    ns = {"re": re, "time": time, "ET": ET, "driver": _FakeDriver(page), "BOUNDS_TOLERANCE": 12}
    exec(src, ns)
    return ns["check_target"]


def test_coordinate_tap_carries_recorded_element():
    r = _result()
    from qagent.models import ElementSignature
    r.steps[1].actions[4].target = ElementSignature(cls="android.widget.Button", bounds=[236, 476, 292, 532], text="Ok")
    code = generate_python_script(r, REQUEST)
    compile(code, "t.py", "exec")
    assert "tap_xy(160, 600, expect={'cls': 'android.widget.Button', 'bounds': (236, 476, 292, 532), " \
           "'text': 'Ok'})" in code


def test_check_target_accepts_same_element_and_small_shift():
    check = _check_target_ns(_PAGE)
    check(264, 504, {"cls": "android.widget.Button", "bounds": (236, 476, 292, 532)}, wait=0)
    check(264, 504, {"cls": "android.widget.Button", "bounds": (240, 470, 296, 530)}, wait=0)  # ±12 px
    check(264, 504, None, wait=0)  # execuções antigas (sem assinatura): comportamento anterior


def test_check_target_fails_when_screen_differs():
    import pytest
    check = _check_target_ns(_PAGE)
    with pytest.raises(AssertionError, match="ecrã diferente da gravação"):   # outro elemento nesse ponto
        check(80, 510, {"cls": "android.widget.Button", "bounds": (40, 300, 120, 370)}, wait=0)
    with pytest.raises(AssertionError, match="ecrã diferente da gravação"):   # mesmo tipo, outro texto
        check(264, 504, {"cls": "android.widget.Button", "bounds": (236, 476, 292, 532), "text": "Pagar"}, wait=0)


def test_signature_keeps_only_stable_text():
    from qagent.agent.recording import record
    from qagent.screen import UiElement
    sr = StepResult(id=1, name="x")
    el = UiElement(ref="e1", cls="android.widget.Button", text="3 itens", desc="Abrir", rid="", bounds=(1, 2, 3, 4))
    record(sr, "tap", el)
    t = sr.actions[0].target
    assert sr.actions[0].strategy == "coordinates" and t.bounds == [1, 2, 3, 4]
    assert t.text is None and t.desc == "Abrir"   # texto com dígitos muda entre execuções → não usado


def test_launcher_tap_before_open_app_is_dropped():
    # Toque num cartão dos recentes (launcher) e depois open_app → o script só abre a app.
    sel = 'new UiSelector().resourceId("com.google.android.apps.nexuslauncher:id/task_view_single").instance(1)'
    s = StepResult(id=1, name="When Abrir a app", status="passed", actions=[
        ActionRecord(tool="tap", strategy="-android uiautomator", selector=sel, result="ok"),
        ActionRecord(tool="list_apps", selector="x", result="1 apps"),
        ActionRecord(tool="open_app", selector="com.example.app", result="restarted"),
        ActionRecord(tool="app_switched", selector="com.example.app", result="ok",
                     value="com.google.android.apps.nexuslauncher")])
    r = ExecutionResult(execution_id="x", record_id="x", created_at="2026-11-13T00:00:00Z", status="passed", steps=[s])
    code = generate_python_script(r, {"testExecution": "t", "platform": "android"})
    compile(code, "t.py", "exec")
    assert "task_view_single" not in code.split("def run_test")[1]
    assert "open_app('com.example.app', restart=True)" in code


def test_app_switch_right_after_open_app_does_not_override_expected_app():
    # open_app seguido de app_switched gravado com outra app do ecrã.
    s = StepResult(id=1, name="When Abre a app", status="passed", actions=[
        ActionRecord(tool="open_app", selector="com.example.pay", result="restarted"),
        ActionRecord(tool="app_switched", selector="com.android.settings", result="ok", value="com.example.shop")])
    r = ExecutionResult(execution_id="x", record_id="x", created_at="2026-11-13T00:00:00Z", status="passed", steps=[s])
    body = generate_python_script(r, {"testExecution": "t", "platform": "android"}).split("def run_test")[1]
    assert "open_app('com.example.pay', restart=True)" in body and "expect_app('com.android.settings')" not in body


def test_foreground_package_prefers_opened_app_then_new_non_system():
    from qagent.agent.tools import foreground_package
    now = {"com.android.settings", "com.example.pay", "com.android.systemui"}
    assert foreground_package(now, {"com.example.shop"}, opened="com.example.pay") == "com.example.pay"
    assert foreground_package({"com.android.systemui", "com.example.pay"}, {"com.example.shop"}) == "com.example.pay"
    assert foreground_package({"com.b.app", "com.a.app"}, {"com.a.app"}) == "com.b.app"   # a nova, não a 1.ª alfabética


def test_close_apps_becomes_close_app_calls_and_home():
    s = StepResult(id=1, name="When Fecha todas as apps", status="passed", actions=[
        ActionRecord(tool="close_apps", selector="com.example.shop,com.example.pay", result="ok"),
        ActionRecord(tool="app_switched", selector="com.google.android.apps.nexuslauncher", result="ok",
                     value="com.example.pay")])
    r = ExecutionResult(execution_id="x", record_id="x", created_at="2026-11-13T00:00:00Z", status="passed", steps=[s])
    code = generate_python_script(r, {"testExecution": "t", "platform": "android"})
    compile(code, "t.py", "exec")
    body = code.split("def run_test")[1]
    assert "close_app('com.example.shop')" in body and "close_app('com.example.pay')" in body
    assert "driver.press_keycode(3)" in body and "expect_app(None)" in body
    assert "manual_step" not in body and "expect_app('com.google.android.apps.nexuslauncher')" not in body


def test_home_screen_is_recognised_by_the_device_home_package_not_by_name():
    from qagent.models import DeviceInfo
    tap_home = ActionRecord(tool="tap", strategy="-android uiautomator",
                            selector='new UiSelector().resourceId("com.vendor.home:id/cell").instance(2)', result="ok")
    tap_bank = ActionRecord(tool="tap", strategy="-android uiautomator",
                            selector='new UiSelector().resourceId("com.example.homebanking:id/menu").instance(2)', result="ok")
    s = StepResult(id=1, name="When Abre a app", status="passed", actions=[
        tap_home, tap_bank, ActionRecord(tool="open_app", selector="com.example.homebanking", result="restarted")])
    r = ExecutionResult(execution_id="x", record_id="x", created_at="2026-11-13T00:00:00Z", status="passed",
                        steps=[s], device=DeviceInfo(udid="emulator-5554", home_package="com.vendor.home"))
    body = generate_python_script(r, {"testExecution": "t", "platform": "android"}).split("def run_test")[1]
    assert "com.vendor.home:id/cell" not in body          # toque no ecrã inicial antes de open_app: omitido
    assert "com.example.homebanking:id/menu" in body      # ".home" no nome não faz dele o ecrã inicial


def test_wait_stable_and_find_scrolls_into_view():
    # Agir sobre uma lista ainda a carregar → toques noutros elementos / elementos não encontrados.
    import time
    code = generate_python_script(_result(), REQUEST)
    compile(code, "t.py", "exec")
    assert "wait_stable(10)" in code.split("def open_app")[1].split("def ")[0]

    class Driver:
        def __init__(self, pages):
            self.pages, self.found = list(pages), []
        @property
        def page_source(self):
            return self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]
        def find_element(self, by, sel):
            self.found.append(sel)
    src = code[code.index("def _scroll_into_view"):code.index("def _dismiss_overlay")]
    ns = {"time": time, "AppiumBy": __import__("appium.webdriver.common.appiumby", fromlist=["AppiumBy"]).AppiumBy}
    exec(src, ns)
    ns["driver"] = Driver(["a", "b", "c", "c"])          # muda duas vezes e depois estabiliza
    t0 = time.time()
    ns["wait_stable"](timeout=5, interval=0.01)
    assert time.time() - t0 < 1
    ns["_scroll_into_view"](ns["AppiumBy"].ID, "pkg:id/item")
    assert 'scrollIntoView(new UiSelector().resourceId("pkg:id/item"))' in ns["driver"].found[0]


def test_generated_free_point_matches_the_agent_rule():
    import re
    import xml.etree.ElementTree as ET
    code = generate_python_script(_result(), REQUEST)
    src = code[code.index("def _bounds"):code.index("def check_target")] + code[code.index("def _free_point"):code.index("def tap(by")]

    class El:
        rect = {"x": 213, "y": 483, "width": 55, "height": 18}

    class Drv:
        page_source = ('<hierarchy><node clickable="true" bounds="[160,300][320,560]">'
                       '<node clickable="false" text="$17.000" bounds="[213,483][268,501]"/></node>'
                       '<node clickable="true" class="android.widget.Button" bounds="[236,476][292,532]"/></hierarchy>')
    ns = {"re": re, "ET": ET, "driver": Drv()}
    exec(src, ns)
    x, y = ns["_free_point"](El())
    assert not (236 <= x <= 292 and 476 <= y <= 532)
