"""Gera um script Python + Appium standalone a partir de uma execução (docs/CPS-geracao-codigo-testes.md).

Determinístico, sem LLM: traduz as ações que FUNCIONARAM (result.json) e os passos estruturados do pedido
(request.json). Estilo alinhado com o Selenium gerado pelo genai_fastapi: executável com `python script.py`,
waits explícitos, pausa de 1 s entre passos.

Segurança: segredos nunca entram no código — `{{secret:nome}}` → os.environ["QAGENT_SECRET_NOME"]; valores
de chaves sensíveis mascarados no request.json ("***") → os.environ["TESTDATA_<CHAVE>"].
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from qagent.models import ExecutionResult, StepResult

_SECRET_REF_RE = re.compile(r"^\{\{\s*secret:([A-Za-z0-9_]+)\s*\}\}$")
_OK = {"ok", "visible", "gone", "restarted"}
_BY = {
    "accessibility id": "AppiumBy.ACCESSIBILITY_ID",
    "id": "AppiumBy.ID",
    "-android uiautomator": "AppiumBy.ANDROID_UIAUTOMATOR",
    "xpath": "AppiumBy.XPATH",
}
_KEYCODES = {"enter": 66, "delete": 67, "tab": 61, "search": 84, "escape": 111, "space": 62, "home": 3}
_SKIP_TOOLS = {"list_apps", "look_at_screen", "get_screen", "appium_find_element"}
# Recurso para execuções sem device.homePackage (gravadas antes de 2026-11-13 ou sem adb).
_LAUNCHER_HINTS = ("launcher", ".home")


def _is_home(text: str | None, home: str | None) -> bool:
    """O texto (package, localizador ou lista de packages) refere o ecrã inicial do dispositivo?"""
    t = text or ""
    if home:  # conhecido: só ele (um package como "com.x.homebanking" não é o ecrã inicial)
        return home in t
    return any(h in t for h in _LAUNCHER_HINTS)
# Ecrãs do sistema (permissões, UI do sistema, instalador): nunca passam a "app esperada" no script.
_SYSTEM_PREFIXES = ("android", "com.android.systemui", "com.google.android.permissioncontroller",
                    "com.android.permissioncontroller", "com.google.android.packageinstaller",
                    "com.android.packageinstaller")


def _q(s: str | None) -> str:
    """Literal Python seguro."""
    return repr(s if s is not None else "")


def _test_data_lines(test_data: dict) -> list[str]:
    lines = ["TEST_DATA = {"]
    for key, raw in test_data.items():
        m = _SECRET_REF_RE.match(str(raw))
        if m:
            env = f"QAGENT_SECRET_{m.group(1).upper()}"
            lines.append(f"    {_q(key)}: os.environ[{_q(env)}],  # segredo")
        elif raw == "***":
            env = f"TESTDATA_{re.sub(r'[^A-Za-z0-9]', '_', key).upper()}"
            lines.append(f"    {_q(key)}: os.environ[{_q(env)}],  # valor sensível")
        else:
            lines.append(f"    {_q(key)}: {_q(str(raw))},")
    lines.append("}")
    return lines


def _expect_literal(target: dict | None) -> str | None:
    """Assinatura do elemento gravado → literal Python para expect= (só campos conhecidos, valores escapados)."""
    if not target or not target.get("cls") or len(target.get("bounds") or []) != 4:
        return None
    parts = [f"'cls': {_q(target['cls'])}", f"'bounds': ({', '.join(str(int(b)) for b in target['bounds'])})"]
    for k in ("text", "desc"):
        if target.get(k):
            parts.append(f"{_q(k)}: {_q(target[k])}")
    return "{" + ", ".join(parts) + "}"


def _loc_call(fn: str, strategy: str | None, selector: str | None, *extra: str,
              target: dict | None = None) -> str | None:
    if strategy == "coordinates" and selector:
        x, y = selector.split(",", 1)
        expect = _expect_literal(target)
        extra = (*extra, f"expect={expect}") if expect else extra
        return f"{fn}_xy({int(x)}, {int(y)}{''.join(', ' + e for e in extra)})"
    by = _BY.get(strategy or "")
    if not by:
        return None
    return f"{fn}({by}, {_q(selector)}{''.join(', ' + e for e in extra)})"


def _recorded_env(result) -> list[str]:
    """G3: ambiente em que o caminho foi gravado (ajuda a perceber falhas do script noutro Android/versão)."""
    dev = result.device
    parts = [p for p in (dev.model, f"Android {dev.platform_version}" if dev.platform_version else None) if p]
    lines = [f"Gravado em: {' · '.join(parts)}"] if parts else []
    if result.app_versions:
        lines.append("Versões das apps: " + ", ".join(f"{p} {v}" for p, v in result.app_versions.items()))
    return lines


def _ai_action_lines(a: dict, fragile: set[tuple[str, str]]) -> list[str]:
    """Uma ação registada de um passo 'ai' → linhas de código (ou [] se não for reproduzível)."""
    tool, strat, sel, val, res = a["tool"], a.get("strategy"), a.get("selector"), a.get("value"), a.get("result")
    if tool == "human_input":  # resultado = "done by user after Ns"
        return [f"manual_step({_q(sel)})"]
    if tool not in ("comment", "assert") and (tool in _SKIP_TOOLS or res not in _OK):
        return []
    warn = ["# ⚠ locator frágil (pode mudar): " + f"{strat}={sel}"] if (strat, sel) in fragile else []
    target = a.get("target")
    if tool == "tap":
        call = _loc_call("tap", strat, sel, target=target)
    elif tool == "long_press":
        call = _loc_call("long_press", strat, sel, target=target)
    elif tool == "type_text":
        call = _loc_call("type_text", strat, sel, f"render({_q(val)})", target=target)
    elif tool == "read_text":
        # Asserção: texto igual ao observado se estável (sem dígitos); senão só presença.
        if val and not any(c.isdigit() for c in val) and strat != "coordinates":
            call = _loc_call("assert_text", strat, sel, _q(val))
        else:
            call = _loc_call("find", strat, sel) if strat != "coordinates" else None
            if call:
                call = f"{call}  # observado na execução: {val!r}"
    elif tool == "scroll_to":
        call = f"scroll_to_selector({_q(sel)})"
    elif tool.startswith("swipe_") or tool.startswith("scroll_"):
        kind, direction = tool.split("_", 1)
        target = _loc_call("find", strat, sel) if strat and strat != "coordinates" else "None"
        call = f"{kind}({_q(direction)}, {target})"
    elif tool == "close_apps":
        pkgs = [p for p in (sel or "").split(",") if p]
        return warn + [f"close_app({_q(p)})" for p in pkgs] + [
            "driver.press_keycode(3)  # home", "expect_app(None)  # apps fechadas: nenhuma app esperada"]
    elif tool == "app_switched":
        if any(sel and sel.startswith(p) for p in _SYSTEM_PREFIXES):
            return [f"# (diálogo/ecrã do sistema na execução original: {sel})"]
        call = f"expect_app({_q(sel)})  # a app mudou para esta durante a execução original"
    elif tool == "wait_for_text":
        call = f"wait_text({_q(sel)}, gone={res == 'gone'}, timeout={float(val or 10):g})"
    elif tool == "wait":
        call = f"time.sleep({float((sel or '1s').rstrip('s')):g})"
    elif tool == "open_app":
        call = f"open_app({_q(sel)}, restart={res == 'restarted'})"
    elif tool.startswith("key_"):
        key = tool[4:]
        call = ("driver.back()" if key == "back" else "hide_keyboard()" if key == "hide_keyboard"
                else f"driver.press_keycode({_KEYCODES[key]})  # {key}" if key in _KEYCODES else None)
    elif tool == "human_input":
        call = f"manual_step({_q(sel)})"
    elif tool == "assert":
        spec = json.loads(val or "{}")
        kind, text = spec.get("kind"), spec.get("text")
        if kind in ("visible", "absent") and "selector" not in spec:
            call = f"wait_text({_q(text)}, gone={kind == 'absent'}, timeout=10)  # asserção do passo"
        elif kind == "visible":
            call = _loc_call("find", strat, sel) + "  # asserção do passo"
        elif kind == "text_equals":
            call = _loc_call("assert_text", strat, sel, _q(text))
        elif kind == "text_contains":
            call = _loc_call("assert_text_contains", strat, sel, _q(text))
        elif kind == "count":
            call = f"assert_count({_BY[strat]}, {_q(sel)}, {_q(spec.get('op', 'eq'))}, {int(spec['count'])})"
        else:
            return [f"# asserção não suportada: {val}"]
    elif tool == "comment":
        return [f"# {sel}  (tratada por ensure_app)"]
    elif tool == "already_done":
        return [f"# ação já feita no {sel}"]
    else:
        return [f"# ação não suportada pelo gerador: {tool} {strat or ''} {sel or ''}".rstrip()]
    return warn + [call] if call else []


def _same_action(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k) for k in ("tool", "strategy", "selector", "value"))


def _drop_interruption_recovery(acts: list[dict], home: str | None = None) -> list[dict]:
    """Não reproduzir literalmente a recuperação de uma interrupção feita pelo agente.

    Padrão: <ação X> → app_switched para OUTRA app (não pedido: não vem de open_app/launcher) →
    open_app(de volta à app anterior) → app_switched (regresso) → <X repetida>. Na repetição a interrupção
    acontece de outra forma (ou não acontece), por isso remove-se a mudança, o regresso e a repetição de X;
    o ensure_app() do script trata as interrupções que surgirem. (Validação 2026-11-12: o alarme do relógio
    apareceu como notificação e o 2.º toque em "Create contact" já não fazia sentido.)"""
    out: list[dict] = []
    i = 0
    while i < len(acts):
        a = acts[i]
        prev = out[-1] if out else None
        unrequested = (a["tool"] == "app_switched" and prev is not None and prev["tool"] not in ("open_app",)
                       and not prev["tool"].startswith("key_")
                       and not _is_home(a.get("value"), home))
        back = acts[i + 1] if i + 1 < len(acts) else None
        if (unrequested and back and back["tool"] == "open_app"
                and back.get("selector") in (a.get("value") or "").split(",")):
            j = i + 2
            if j < len(acts) and acts[j]["tool"] == "app_switched":
                j += 1  # app_switched do regresso
            if j < len(acts) and prev is not None and _same_action(acts[j], prev):
                j += 1  # ação repetida depois do regresso
            out.append({"tool": "comment", "selector": f"interrupção na execução original ({a.get('selector')})"})
            i = j
            continue
        out.append(a)
        i += 1
    return out


def _structured_lines(step: dict) -> list[str]:
    """Passo estruturado do pedido (sem LLM) → código."""
    act = step["action"]
    loc = step.get("locator") or {}
    strat, sel = loc.get("strategy"), loc.get("value")
    t = step.get("timeoutSec", 10)
    if act == "tap":
        return [_loc_call("tap", strat, sel) or "# locator não suportado"]
    if act == "type":
        return [_loc_call("type_text", strat, sel, f"render({_q(step.get('text'))})") or "# locator não suportado"]
    if act == "scroll_to":
        return [f"scroll_to_selector({_q(sel)})" if strat == "-android uiautomator" else
                (_loc_call("find", strat, sel) or "# locator não suportado")]
    if act == "assert_visible":
        return [_loc_call("find", strat, sel, f"timeout={t}") or "# locator não suportado"]
    if act == "assert_text":
        fn = "assert_text_contains" if step.get("contains") else "assert_text"
        return [_loc_call(fn, strat, sel, f"render({_q(step.get('text'))})") or "# locator não suportado"]
    if act == "back":
        return ["driver.back()"]
    if act == "wait":
        return [f"time.sleep({t})"]
    if act == "manual":
        return [f"manual_step({_q(step.get('text'))})"]
    return [f"# ação estruturada não suportada: {act}"]


def _step_block(i: int, sr: StepResult, req_step: dict | None, home: str | None = None) -> list[str]:
    head = [f"    # ── Passo {i}: {sr.name}  [{sr.status}]"]
    if sr.status == "skipped":
        return head + ["    # não executado na execução original"]
    body: list[str] = []
    if req_step and req_step.get("action") != "ai":
        body = _structured_lines(req_step)
    else:
        fragile = {(l.strategy, l.value) for l in sr.locators if l.fragile}
        acts = _drop_interruption_recovery([a.model_dump() for a in sr.actions], home)
        for k, a in enumerate(acts):
            nxt = acts[k + 1] if k + 1 < len(acts) else None
            if a["tool"] == "app_switched" and k > 0 and acts[k - 1].get("_replaced"):
                continue  # já convertido em open_app
            if a["tool"] == "app_switched" and k > 0 and acts[k - 1]["tool"] in ("open_app", "close_apps"):
                # open_app já define a app esperada; uma mudança registada a seguir não a deve substituir.
                continue
            if (a["tool"] == "tap" and nxt and nxt["tool"] == "app_switched"
                    and _is_home(nxt.get("value"), home)):
                # Abrir uma app tocando num ícone do launcher depende da posição dos ícones → open_app.
                body.append(f"open_app({_q(nxt['selector'])})  # na execução original: toque no ícone do launcher")
                a["_replaced"] = True
                continue
            if (a["tool"] in ("tap", "long_press", "swipe_left", "swipe_right", "swipe_up", "swipe_down")
                    and _is_home(a.get("selector"), home)
                    and any(b["tool"] == "open_app" for b in acts[k + 1:])):
                # Toque no ecrã inicial/recentes seguido de open_app: repeti-lo dependeria do estado do launcher.
                body.append("# (toque no launcher/recentes da execução original omitido: a app é aberta por open_app)")
                continue
            body += _ai_action_lines(a, fragile)
    if sr.status != "passed":
        body.append(f"raise AssertionError({_q(f'Passo {i} {sr.status} na execução original: {sr.reason}')})")
    if not body:
        body = ["pass  # nenhuma ação reproduzível registada"]
    return head + [f"    {ln}" for ln in body] + ["    time.sleep(STEP_PAUSE)", ""]


def generate_python_script(result: ExecutionResult, request: dict) -> str:
    android = ((request.get("app") or {}).get("android") or {})
    package, activity, apk = android.get("appPackage"), android.get("appActivity"), android.get("app")
    opts = request.get("options") or {}
    req_steps = request.get("steps") or []
    title = (request.get("scenario") or {}).get("name") or request.get("testExecution") or "Teste QAgent"
    fragile_count = sum(1 for s in result.steps for l in s.locators if l.fragile)
    secrets = [m.group(1).upper() for v in (request.get("testData") or {}).values()
               if (m := _SECRET_REF_RE.match(str(v)))]
    sensitive = [k for k, v in (request.get("testData") or {}).items() if v == "***"]

    caps = ["    options = UiAutomator2Options()",
            "    options.udid = os.environ.get('DEVICE_UDID', " + _q(result.device.udid or "emulator-5554") + ")",
            "    options.new_command_timeout = 300",
            "    options.auto_grant_permissions = True"]
    if apk:
        caps.append(f"    options.app = {_q(apk)}")
    if package:
        caps.append(f"    options.app_package = {_q(package)}")
        if activity:
            caps.append(f"    options.app_activity = {_q(activity)}")
        caps.append("    options.set_capability('appium:appWaitActivity', '*')")
        caps.append("    options.no_reset = True  # estado limpo só para as apps em RESET_APPS (como no QAgent)")
    else:
        caps.append("    options.no_reset = True  # sem app: começa no ecrã inicial do dispositivo")
        caps.append("    options.set_capability('appium:autoLaunch', False)")

    header = [
        "#!/usr/bin/env python3",
        '"""Teste gerado pelo QAgent (sem LLM) a partir das ações executadas.',
        "",
        f"Execução: {result.execution_id}  |  estado original: {result.status}  |  gerado: "
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        f"Caso: {title}",
        *_recorded_env(result),
        "",
        "Requisitos:",
        "  pip install Appium-Python-Client",
        "  Servidor Appium 2/3 com o driver uiautomator2 em APPIUM_SERVER (omissão http://127.0.0.1:4723)",
        "  Dispositivo/emulador ligado (DEVICE_UDID, omissão o da execução original)",
    ]
    if secrets or sensitive:
        header.append("Variáveis de ambiente obrigatórias (segredos — nunca escritos neste ficheiro):")
        header += [f"  QAGENT_SECRET_{s}" for s in secrets]
        header += [f"  TESTDATA_{re.sub(r'[^A-Za-z0-9]', '_', k).upper()}" for k in sensitive]
    if fragile_count:
        header.append(f"Atenção: {fragile_count} locator(s) frágeis (coordenadas, índice ou texto dinâmico) — "
                      "marcados com ⚠ no código.")
    if result.status != "passed":
        header.append("Atenção: a execução original NÃO passou; o script reproduz o caminho até à falha.")
    header += ['"""', ""]

    lines = header + [
        "import os",
        "import re",
        "import time",
        "import xml.etree.ElementTree as ET",
        "",
        "from appium import webdriver",
        "from appium.options.android import UiAutomator2Options",
        "from appium.webdriver.common.appiumby import AppiumBy",
        "from selenium.common.exceptions import TimeoutException",
        "from selenium.webdriver.support import expected_conditions as EC",
        "from selenium.webdriver.support.ui import WebDriverWait",
        "",
        "APPIUM_SERVER = os.environ.get('APPIUM_SERVER', 'http://127.0.0.1:4723')",
        "BOUNDS_TOLERANCE = 12  # px: toques por coordenadas só se o elemento gravado estiver no mesmo sítio",
        "# Pausa entre passos, em segundos (o script já espera que o ecrã estabilize; isto é tempo extra para",
        "# acompanhar a execução). Mudar sem editar o script: $env:STEP_PAUSE = '3' (PowerShell).",
        "STEP_PAUSE = float(os.environ.get('STEP_PAUSE', '1.0'))",
        "TIMEOUT = 15",
        f"RESET_APPS = {opts.get('resetApps') or []!r}",
        "",
        *_test_data_lines(request.get("testData") or {}),
        "",
        "driver = None",
        "",
        "",
        "def make_driver():",
        *caps,
        "    d = webdriver.Remote(APPIUM_SERVER, options=options)",
        "    # Incluir todas as janelas (notificações, diálogos do sistema) no page source: deteção de sobreposições.",
        "    d.update_settings({'enableMultiWindows': True})",
        "    return d",
        "",
        "",
        "def render(template):",
        "    return re.sub(r'\\{\\{\\s*testData\\.([A-Za-z0-9_]+)\\s*\\}\\}', lambda m: TEST_DATA[m.group(1)], template)",
        "",
        "",
        "EXPECTED_APP = None  # app em que o teste devia estar (definida por open_app/expect_app)",
        f"SYSTEM_PACKAGES = {set(_SYSTEM_PREFIXES)!r}",
        "",
        "",
        "def expect_app(package):",
        "    global EXPECTED_APP",
        "    EXPECTED_APP = package",
        "",
        "",
        "# Diálogos de permissões do Android (ids standard, independentes do idioma) — aceites, como faz a",
        "# capability autoGrantPermissions na instalação.",
        "PERMISSION_ALLOW_IDS = [",
        "    'com.android.permissioncontroller:id/permission_allow_button',",
        "    'com.android.permissioncontroller:id/permission_allow_foreground_only_button',",
        "    'com.android.permissioncontroller:id/permission_allow_one_time_button',",
        "    'com.android.packageinstaller:id/permission_allow_button',",
        "]",
        "",
        "",
        "def handle_permission_dialog():",
        "    for rid in PERMISSION_ALLOW_IDS:",
        "        found = driver.find_elements(AppiumBy.ID, rid)",
        "        if found:",
        "            found[0].click()",
        "            print('[aviso] diálogo de permissões do Android aceite')",
        "            time.sleep(1)",
        "            return True",
        "    return False",
        "",
        "",
        "def ensure_app():",
        "    \"\"\"Interrupções (alarme, chamada, outra app à frente): voltar à app esperada antes de agir.\"\"\"",
        "    current = driver.current_package",
        "    if current in SYSTEM_PACKAGES:",
        "        handle_permission_dialog()  # diálogo do sistema: aceitar permissões, não fechar a app",
        "        return",
        "    if EXPECTED_APP and current != EXPECTED_APP:",
        "        print(f'[aviso] interrupção: {current} à frente; a voltar a {EXPECTED_APP}')",
        "        driver.activate_app(EXPECTED_APP)",
        "        time.sleep(1)",
        "",
        "",
        "def find(by, value, timeout=TIMEOUT):",
        "    \"\"\"Procura o elemento; se não aparecer logo, desliza a lista até ele (a distância de cada scroll varia",
        "    entre a execução original e o script, por isso não se confia só nos scrolls gravados).\"\"\"",
        "    ensure_app()",
        "    try:",
        "        return WebDriverWait(driver, min(3, timeout)).until(EC.presence_of_element_located((by, value)))",
        "    except TimeoutException:",
        "        _scroll_into_view(by, value)",
        "    return WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, value)))",
        "",
        "",
        "def _scroll_into_view(by, value):",
        "    sel = {AppiumBy.ANDROID_UIAUTOMATOR: value,",
        "           AppiumBy.ID: f'new UiSelector().resourceId(\"{value}\")',",
        "           AppiumBy.ACCESSIBILITY_ID: f'new UiSelector().description(\"{value}\")'}.get(by)",
        "    if not sel or 'UiScrollable' in sel:",
        "        return",
        "    try:",
        "        driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR,",
        "                            f'new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView({sel})')",
        "    except Exception:",
        "        pass  # sem lista deslizável ou elemento inexistente: o find seguinte decide",
        "",
        "",
        "def wait_stable(timeout=6, interval=0.5):",
        "    \"\"\"Esperar que o ecrã deixe de mudar (carregamentos, animações), como o agente faz depois de cada ação.",
        "    Sem isto, o script agia sobre listas ainda a carregar e os toques caíam noutros elementos.\"\"\"",
        "    prev, end = None, time.time() + timeout",
        "    while time.time() < end:",
        "        cur = _snapshot()",
        "        if cur and cur == prev:",
        "            return",
        "        prev = cur",
        "        time.sleep(interval)",
        "",
        "",
        "def _snapshot():",
        "    try:",
        "        return driver.page_source",
        "    except Exception:",
        "        return ''",
        "",
        "",
        "def _dismiss_overlay():",
        "    s = driver.get_window_size()",
        "    driver.execute_script('mobile: swipeGesture', {'left': int(s['width'] * 0.1), 'top': 0,",
        "                          'width': int(s['width'] * 0.8), 'height': int(s['height'] * 0.25),",
        "                          'direction': 'up', 'percent': 0.9})",
        "    time.sleep(1)",
        "",
        "",
        "def _free_point(el):",
        "    \"\"\"Se o CENTRO do elemento estiver tapado por outro elemento clicável (botão flutuante, barra fixa…),",
        "    devolve um ponto livre do próprio elemento; senão None. Igual a qagent.screen.free_point.\"\"\"",
        "    r = el.rect",
        "    t = (r['x'], r['y'], r['x'] + r['width'], r['y'] + r['height'])",
        "    cx, cy = (t[0] + t[2]) // 2, (t[1] + t[3]) // 2",
        "    inside = lambda a, b: b[0] <= a[0] and b[1] <= a[1] and a[2] <= b[2] and a[3] <= b[3]",
        "    has = lambda b, x, y: b[0] <= x <= b[2] and b[1] <= y <= b[3]",
        "    try:",
        "        nodes = ET.fromstring(driver.page_source.encode('utf-8')).iter()",
        "    except Exception:",
        "        return None",
        "    covers = [b for n in nodes if n.get('clickable') == 'true' and (b := _bounds(n.get('bounds')))",
        "              and has(b, cx, cy) and not inside(t, b) and not inside(b, t)]",
        "    if not covers:",
        "        return None",
        "    grid = (0.5, 0.25, 0.75, 0.1, 0.9)",
        "    for fy in grid:",
        "        for fx in grid:",
        "            x, y = int(t[0] + (t[2] - t[0]) * fx), int(t[1] + (t[3] - t[1]) * fy)",
        "            if not any(has(b, x, y) for b in covers):",
        "                return x, y",
        "    return None",
        "",
        "",
        "def tap(by, value):",
        "    \"\"\"Toque com proteção contra sobreposições do sistema (ex.: notificação heads-up por cima do botão).",
        "    Só repete se o ecrã NÃO mudou e há uma janela do sistema visível — evita duplicar ações.\"\"\"",
        "    ensure_app()",
        "    el = find(by, value)",
        "    before = _snapshot()",
        "    pt = _free_point(el)",
        "    if pt:",
        "        print(f'[aviso] centro de {value!r} tapado por outro elemento; a tocar em {pt}')",
        "        driver.execute_script('mobile: clickGesture', {'x': pt[0], 'y': pt[1]})",
        "    else:",
        "        el.click()",
        "    time.sleep(0.6)",
        "    after = _snapshot()",
        "    if after == before and 'package=\"com.android.systemui\"' in after:",
        "        print('[aviso] sobreposição do sistema por cima do elemento; a afastá-la e a repetir o toque')",
        "        _dismiss_overlay()",
        "        WebDriverWait(driver, TIMEOUT).until(EC.element_to_be_clickable((by, value))).click()",
        "    wait_stable()",
        "",
        "",
        "def _bounds(s):",
        "    n = [int(v) for v in re.findall(r'-?\\d+', s or '')]",
        "    return tuple(n) if len(n) == 4 else None",
        "",
        "",
        "def check_target(x, y, expect, wait=5):",
        "    \"\"\"Toque por coordenadas: confirmar que o elemento da gravação está neste ponto (mesma classe, posição",
        "    ±BOUNDS_TOLERANCE px e, se gravado, o mesmo texto). Senão falha em vez de tocar às cegas noutra coisa.\"\"\"",
        "    if not expect:",
        "        return",
        "    here, deadline = [], time.time() + wait",
        "    while True:",
        "        try:",
        "            root = ET.fromstring(driver.page_source.encode('utf-8'))",
        "        except Exception:",
        "            root = None",
        "        here = []",
        "        for node in (root.iter() if root is not None else []):",
        "            b = _bounds(node.get('bounds'))",
        "            if not b or not (b[0] <= x <= b[2] and b[1] <= y <= b[3]):",
        "                continue",
        "            cls, text, desc = node.get('class') or node.tag, node.get('text') or None, node.get('content-desc') or None",
        "            here.append((cls, b, text or desc))",
        "            if (cls == expect['cls'] and all(abs(p - q) <= BOUNDS_TOLERANCE for p, q in zip(b, expect['bounds']))",
        "                    and expect.get('text') in (None, text) and expect.get('desc') in (None, desc)):",
        "                return",
        "        if time.time() >= deadline:",
        "            break",
        "        time.sleep(0.5)",
        "    raise AssertionError(f'ecrã diferente da gravação: em ({x}, {y}) esperava {expect}; '",
        "                         f'encontrado (mais interior por último): {here[-3:]}')",
        "",
        "",
        "def tap_xy(x, y, expect=None):",
        "    ensure_app()",
        "    check_target(x, y, expect)",
        "    driver.execute_script('mobile: clickGesture', {'x': x, 'y': y})",
        "    wait_stable()",
        "",
        "",
        "def long_press(by, value):",
        "    driver.execute_script('mobile: longClickGesture', {'elementId': find(by, value).id})",
        "",
        "",
        "def long_press_xy(x, y, expect=None):",
        "    ensure_app()",
        "    check_target(x, y, expect)",
        "    driver.execute_script('mobile: longClickGesture', {'x': x, 'y': y})",
        "",
        "",
        "def type_text(by, value, text):",
        "    el = find(by, value)",
        "    el.clear()",
        "    el.send_keys(text)",
        "",
        "",
        "def type_text_xy(x, y, text, expect=None):",
        "    tap_xy(x, y, expect)",
        "    driver.switch_to.active_element.send_keys(text)",
        "",
        "",
        "def assert_text(by, value, expected):",
        "    actual = find(by, value).text",
        "    assert actual == expected, f'texto {actual!r} != esperado {expected!r}'",
        "",
        "",
        "def assert_text_contains(by, value, expected):",
        "    actual = find(by, value).text",
        "    assert expected in actual, f'texto {actual!r} não contém {expected!r}'",
        "",
        "",
        "def assert_count(by, value, op, expected):",
        "    find(by, value)",
        "    n = len(driver.find_elements(by, value))",
        "    ok = n == expected if op == 'eq' else n >= expected",
        "    assert ok, f'{n} elemento(s) {value!r}; esperado ' + ('' if op == 'eq' else '>= ') + str(expected)",
        "",
        "",
        "def _area(element):",
        "    if element is not None:",
        "        return {'elementId': element.id}",
        "    s = driver.get_window_size()",
        "    return {'left': int(s['width'] * 0.1), 'top': int(s['height'] * 0.2),",
        "            'width': int(s['width'] * 0.8), 'height': int(s['height'] * 0.6)}",
        "",
        "",
        "def swipe(direction, element=None):",
        "    ensure_app()",
        "    driver.execute_script('mobile: swipeGesture', {**_area(element), 'direction': direction, 'percent': 0.75})",
        "    wait_stable()",
        "",
        "",
        "def scroll(direction, element=None):",
        "    ensure_app()",
        "    driver.execute_script('mobile: scrollGesture', {**_area(element), 'direction': direction, 'percent': 0.75})",
        "    wait_stable()",
        "",
        "",
        "def scroll_to_selector(ui_selector):",
        "    ensure_app()",
        "    driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR,",
        "                        f'new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView({ui_selector})')",
        "",
        "",
        "def text_regex(text):",
        "    \"\"\"Regex (Java) para textMatches SEM barras invertidas: o parser de UiSelector do Appium não as",
        "    interpreta ('\\\\.' ficava uma barra literal e o texto nunca era encontrado). Especiais → [c].\"\"\"",
        "    out = []",
        "    for c in text:",
        "        if c.isalnum() or c == ' ':",
        "            out.append(c)",
        "        elif c in '\"\\\\[]^&':",
        "            out.append('.')",
        "        else:",
        "            out.append('[' + c + ']')",
        "    return '(?isu).*' + ''.join(out) + '.*'",
        "",
        "",
        "def wait_text(text, gone=False, timeout=10):",
        "    pattern = text_regex(text)",
        "    ensure_app()",
        "    def present(_):",
        "        for attr in ('textMatches', 'descriptionMatches'):",
        "            if driver.find_elements(AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().{attr}(\"{pattern}\")'):",
        "                return True",
        "        return False",
        "    try:",
        "        WebDriverWait(driver, timeout, poll_frequency=0.7).until(lambda d: present(d) != gone)",
        "    except TimeoutException:",
        "        raise AssertionError(f'{text!r} ' + ('ainda visível' if gone else 'não visível') + f' após {timeout}s')",
        "",
        "",
        "def open_app(package, restart=False):",
        "    expect_app(package)",
        "    if restart:",
        "        driver.terminate_app(package)",
        "    driver.activate_app(package)",
        "    end = time.time() + 15  # esperar que a app fique à frente (arranque a frio) antes do passo seguinte",
        "    while driver.current_package != package and time.time() < end:",
        "        time.sleep(0.5)",
        "    wait_stable(10)  # a app pode mostrar o ecrã antes de acabar de carregar o conteúdo",
        "",
        "",
        "def close_app(package):",
        "    try:",
        "        driver.terminate_app(package)",
        "    except Exception:",
        "        pass  # já não estava a correr",
        "",
        "",
        "def hide_keyboard():",
        "    try:",
        "        driver.hide_keyboard()",
        "    except Exception:",
        "        pass",
        "",
        "",
        "def manual_step(instruction):",
        "    input(f'[AÇÃO MANUAL] {instruction} — prima Enter para continuar... ')",
        "",
        "",
        "def run_test():",
        "    for package in RESET_APPS:",
        "        driver.execute_script('mobile: clearApp', {'appId': package})",
        *([f"    driver.activate_app({_q(package)})  # limpar os dados fecha a app em teste", ""]
          if package and package in (opts.get("resetApps") or []) else [""]),
    ]
    for i, sr in enumerate(result.steps, 1):
        req_step = req_steps[i - 1] if i - 1 < len(req_steps) else None
        lines += _step_block(i, sr, req_step, result.device.home_package)
    lines += [
        "",
        "if __name__ == '__main__':",
        "    driver = make_driver()",
        "    try:",
        "        run_test()",
        "        print('PASSED')",
        "    finally:",
        "        driver.quit()",
        "",
    ]
    return "\n".join(lines)


def load_request(run_dir) -> dict:
    return json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
