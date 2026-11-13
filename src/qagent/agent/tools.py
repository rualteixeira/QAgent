"""Ferramentas genéricas expostas ao LLM num passo. O LLM refere elementos por `ref` do último ecrã; aqui a ref
é convertida no locator mais estável e registada. Depois de cada ação que muda o ecrã, o resultado traz o ecrã
novo (relido até estabilizar)."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path

from langchain_core.tools import StructuredTool

from qagent.agent import schemas as S
from qagent.agent.device import Device
from qagent.agent.errors import HumanInputRequired, ToolMisuse
from qagent.agent.navigation import AppNavigator, package_matches_step
from qagent.agent.recording import Secrets, record, record_point
from qagent.agent.state import StepState
from qagent.executor import StepFailed, render
from qagent.mcp_client import ToolError
from qagent.models import ActionRecord, StepResult
from qagent.screen import SYSTEM_PACKAGES, node_at, png_size

# Recurso quando não se consegue perguntar ao Android qual é o ecrã inicial (ex.: dispositivo remoto sem adb).
_LAUNCHER_HINTS = ("launcher", ".home")

# Ferramentas que não contam para o orçamento de ações do passo.
FREE_TOOLS = frozenset({"get_screen", "read_text", "look_at_screen", "list_apps", "request_human"})
# Ferramentas que podem repetir-se com os mesmos argumentos sem serem recusadas.
REPEATABLE_TOOLS = frozenset({"wait", "scroll", "swipe", "drag"})


def foreground_package(pkgs_now: set[str], pkgs_before: set[str], opened: str | None = None) -> str:
    """App que passou a estar à frente. O ecrã pode ter elementos de várias apps; escolher a 1.ª por ordem
    alfabética registava a app errada e o script gerado "voltava" para ela.
    Ordem: a app pedida (open_app) > nova e não do sistema > não do sistema."""
    if opened and opened in pkgs_now:
        return opened
    return (sorted(pkgs_now - pkgs_before - SYSTEM_PACKAGES) or sorted(pkgs_now - SYSTEM_PACKAGES)
            or sorted(pkgs_now))[0]


class StepTools:
    def __init__(self, device: Device, nav: AppNavigator, secrets: Secrets, state: StepState,
                 result: StepResult) -> None:
        self.d, self.nav, self.secrets, self.st, self.result = device, nav, secrets, state, result

    async def _act(self, fn, *, show_screen: bool = True, is_action: bool = True,
                   requested_switch: bool = False, opened: str | None = None) -> str:
        """Executa uma ferramenta: contabiliza sucesso/falha, devolve o ecrã novo e deteta mudanças de app."""
        d, st, result = self.d, self.st, self.result
        before = d.describe() if show_screen else None
        try:
            msg = await fn()
        except ToolMisuse as e:
            return f"ERROR: {e}"
        except StepFailed as e:
            if is_action:
                st.action_failures += 1
            return f"FAILED: {e}\nCurrent screen:\n{await d.screen_text()}"
        except ToolError as e:
            if is_action:
                st.action_failures += 1
            return f"ERROR: {str(e)[:300]}\nCurrent screen:\n{await d.screen_text()}"
        st.successes += 1
        if is_action:
            st.action_successes += 1
        if not show_screen:
            return f"OK. {msg}"
        pkgs_before = d.packages()
        screen_now = await d.settled_screen(before)
        pkgs_now = d.packages()
        warn = ""
        switched = bool(pkgs_before and pkgs_now and not (pkgs_now & pkgs_before))
        if switched:
            # Para a geração de código: que app passou a estar à frente e a partir de onde.
            result.actions.append(ActionRecord(tool="app_switched",
                                               selector=foreground_package(pkgs_now, pkgs_before, opened),
                                               result="ok", value=",".join(sorted(pkgs_before))))
        if switched and not requested_switch:
            # Interrupção (alarme, chamada, outra app): a ação pode ter sido engolida.
            warn = (f"\nWARNING: the foreground app changed from {sorted(pkgs_before)} to "
                    f"{sorted(pkgs_now)} after this action without you asking. Your action may not "
                    "have taken effect: return to the app (open_app) and confirm before finishing.")
        return f"OK. {msg}{warn}\nScreen now:\n{screen_now}"

    # ---------- ferramentas ----------

    async def tap(self, ref: str) -> str:
        async def do():
            el = self.d.element(ref)
            free = self.d.unobstructed_point(el)
            el_id = None if free else await self.d.find(el)
            if el_id:
                await self.d.gesture({"action": "tap", "elementUUID": el_id})
            else:
                x, y = free or el.center  # centro tapado por outro elemento → ponto livre do próprio elemento
                await self.d.gesture({"action": "tap", "x": x, "y": y})
            record(self.result, "tap", el)
            return f"Tapped {ref} ({el.label or el.cls.rsplit('.', 1)[-1]})."
        return await self._act(do)

    async def long_press(self, ref: str) -> str:
        async def do():
            el = self.d.element(ref)
            el_id = await self.d.find(el)
            args = {"action": "long_press", "elementUUID": el_id} if el_id else \
                {"action": "long_press", "x": el.center[0], "y": el.center[1]}
            await self.d.gesture(args)
            record(self.result, "long_press", el)
            return f"Long-pressed {ref}."
        return await self._act(do)

    async def type_text(self, ref: str, text: str, submit: bool = False) -> str:
        async def do():
            el = self.d.element(ref)
            value = render(text, self.secrets.data)
            el_id = await self.d.find(el)
            if el_id:
                await self.d.set_value({"elementUUID": el_id, "text": value})
            else:
                x, y = el.center
                await self.d.gesture({"action": "tap", "x": x, "y": y})
                await self.d.set_value({"text": value, "w3cActions": True})
            record(self.result, "type_text", el, value=self.secrets.mask(text))
            if submit:
                await self.d.key("enter")
                self.result.actions.append(ActionRecord(tool="key_enter", result="ok"))
            shown = "***" if value != text else repr(value)
            return f"Typed {shown} into {ref}" + (" and pressed Enter." if submit else ".")
        return await self._act(do, show_screen=submit)

    async def read_text(self, ref: str) -> str:
        async def do():
            await self.d.read_screen()  # leitura fresca
            el = self.d.element(ref)
            observed = el.text or el.desc or " / ".join(el.inner_texts)
            record(self.result, "read_text", el, value=self.secrets.mask(observed))
            state = []
            if el.checkable:
                state.append("checked" if el.checked else "unchecked")
            if el.selected:
                state.append("selected")
            if not el.enabled:
                state.append("disabled")
            return (f'{ref}: text="{el.text}" desc="{el.desc}"'
                    + (f' contains="{" / ".join(el.inner_texts)}"' if el.inner_texts else "")
                    + (f" state={state}" if state else ""))
        return await self._act(do, show_screen=False, is_action=False)

    async def _directional(self, action: str, direction: str, ref: str | None):
        args = {"action": action, "direction": direction}
        el = None
        if ref:
            el = self.d.element(ref)
            el_id = await self.d.find(el)
            if el_id:
                args["elementUUID"] = el_id
        return args, el

    async def swipe(self, direction: str, ref: str | None = None) -> str:
        async def do():
            args, el = await self._directional("swipe", direction, ref)
            await self.d.gesture(args)
            record(self.result, f"swipe_{direction}", el)
            return f"Swiped {direction}."
        return await self._act(do)

    async def scroll(self, direction: str, ref: str | None = None) -> str:
        async def do():
            args, el = await self._directional("scroll", direction, ref)
            before = self.d.describe()
            await self.d.gesture(args)
            record(self.result, f"scroll_{direction}", el)
            await asyncio.sleep(0.5)
            if before is not None and (await self.d.read_screen()).describe() == before:
                # Sem isto o modelo pode repetir scrolls no fim da lista sem perceber que não há mais conteúdo.
                raise StepFailed(f"end of content: nothing changed after scrolling {direction} — there is "
                                 "no more content in that direction")
            return f"Scrolled {direction}."
        return await self._act(do)

    async def scroll_to_text(self, text: str, direction: str = "down") -> str:
        async def do():
            safe = text.replace("\\", "\\\\").replace('"', '\\"')
            last: Exception | None = None
            for sel in (f'new UiSelector().textContains("{safe}")',
                        f'new UiSelector().descriptionContains("{safe}")'):
                try:
                    await self.d.gesture({"action": "scroll_to_element", "strategy": "-android uiautomator",
                                          "selector": sel, "direction": direction})
                    self.result.actions.append(ActionRecord(tool="scroll_to", strategy="-android uiautomator",
                                                            selector=sel, result="ok"))
                    return f"'{text}' is now visible."
                except ToolError as e:
                    last = e
            raise StepFailed(f"'{text}' not found after scrolling {direction}") from last
        return await self._act(do)

    async def press_key(self, key: str) -> str:
        async def do():
            await self.d.key(key)
            self.result.actions.append(ActionRecord(tool=f"key_{key}", result="ok"))
            return f"Pressed {key}."
        return await self._act(do, requested_switch=True)

    async def wait(self, seconds: float) -> str:
        async def do():
            await asyncio.sleep(seconds)
            self.result.actions.append(ActionRecord(tool="wait", selector=f"{seconds:g}s", result="ok"))
            return f"Waited {seconds:g}s."
        return await self._act(do, is_action=False)

    async def wait_for_text(self, text: str, timeout_sec: float = 10, gone: bool = False) -> str:
        async def do():
            needle, deadline = text.lower(), time.monotonic() + timeout_sec
            while True:
                screen = await self.d.read_screen()
                present = any(needle in t.lower() for t in screen.texts())
                if present != gone:
                    self.result.actions.append(ActionRecord(
                        tool="wait_for_text", selector=self.secrets.mask(text), result="gone" if gone else "visible",
                        value=f"{timeout_sec:g}"))
                    return f"'{text}' is {'gone' if gone else 'visible'}."
                if time.monotonic() >= deadline:
                    self.result.actions.append(ActionRecord(
                        tool="wait_for_text", selector=text, result=f"timeout {timeout_sec:g}s"))
                    raise StepFailed(f"'{text}' {'still visible' if gone else 'not visible'} "
                                     f"after {timeout_sec:g}s")
                await asyncio.sleep(0.7)
        return await self._act(do, is_action=False)

    async def look_at_screen(self) -> str:
        path = await self.d.screenshot()
        data = Path(path).read_bytes()
        self.st.pending_image = base64.b64encode(data).decode()
        self.st.shot_size = png_size(data)
        self.result.actions.append(ActionRecord(tool="look_at_screen", result="ok"))
        size = f" ({self.st.shot_size[0]}x{self.st.shot_size[1]} px)" if self.st.shot_size else ""
        return (f"Screenshot{size} attached in the next message (refs from the latest screen description still "
                "apply; tap_point / long_press_point use positions in this screenshot).")

    async def _point(self, gesture: str, x: int, y: int) -> str:
        """Interfaces desenhadas sem acessibilidade (o modelo vê-as na captura mas não estão na descrição): agir
        num ponto. A posição vem em pixels da captura, que pode estar reduzida → converte-se para o ecrã real."""
        async def do():
            px, py = self._to_screen(x, y, prefer_ref=True)
            await self.d.gesture({"action": gesture, "x": px, "y": py})
            record_point(self.result, gesture, px, py, node_at(self.d.xml, px, py))
            return f"{'Tapped' if gesture == 'tap' else 'Long-pressed'} at ({px},{py}) on the screen."
        return await self._act(do)

    def _to_screen(self, x: int, y: int, *, prefer_ref: bool) -> tuple[int, int]:
        """Posição da captura → ecrã real (a captura pode estar reduzida). Com prefer_ref, um ponto dentro de um
        controlo LISTADO e pequeno é recusado: deve usar-se a ref (localizador estável)."""
        if not self.st.shot_size:
            raise ToolMisuse("call look_at_screen first: positions are only for content you can see in the "
                             "screenshot but that is not listed in the screen description")
        sw, sh = self.st.shot_size
        if not (0 <= x < sw and 0 <= y < sh):
            raise ToolMisuse(f"point ({x},{y}) is outside the screenshot ({sw}x{sh} px)")
        scr = self.d.screen
        w, h = (scr.width, scr.height) if scr and scr.width and scr.height else (sw, sh)
        px, py = round(x * w / sw), round(y * h / sh)
        el = self.d.element_at(px, py)
        if prefer_ref and el and (el.clickable or el.long_clickable or el.checkable or el.editable) and \
                (el.bounds[2] - el.bounds[0]) * (el.bounds[3] - el.bounds[1]) < 0.25 * w * h:
            raise ToolMisuse(f"that point is inside listed element {el.ref} "
                             f"({el.label or el.cls.rsplit('.', 1)[-1]}): use ref={el.ref} instead")
        return px, py

    async def drag(self, from_ref: str | None = None, from_x: int | None = None, from_y: int | None = None,
                   to_ref: str | None = None, to_x: int | None = None, to_y: int | None = None,
                   hold: bool = True) -> str:
        """Arrastar de um elemento/ponto para outro. hold=True: premir, manter e mover (mover/reordenar itens,
        appium_drag_and_drop); hold=False: mover diretamente (sliders, desenhar; gesto com início e fim)."""
        async def do():
            if bool(from_ref) == (from_x is not None and from_y is not None):
                raise ToolMisuse("give the start as from_ref OR from_x+from_y")
            if bool(to_ref) == (to_x is not None and to_y is not None):
                raise ToolMisuse("give the end as to_ref OR to_x+to_y")
            src_el = self.d.element(from_ref) if from_ref else None
            dst_el = self.d.element(to_ref) if to_ref else None
            src = src_el.center if src_el else self._to_screen(from_x, from_y, prefer_ref=True)
            dst = dst_el.center if dst_el else self._to_screen(to_x, to_y, prefer_ref=False)
            if hold:
                args = {"sourceX": src[0], "sourceY": src[1], "targetX": dst[0], "targetY": dst[1]}
                if src_el and (sid := await self.d.find(src_el)):
                    args = {"sourceElementUUID": sid, **{k: v for k, v in args.items() if k.startswith("target")}}
                if dst_el and (tid := await self.d.find(dst_el)):
                    args = {**{k: v for k, v in args.items() if k.startswith("source")}, "targetElementUUID": tid}
                await self.d.conn.call("appium_drag_and_drop", {**args, "sessionId": self.d.sid})
            else:
                await self.d.gesture({"action": "swipe", "x": src[0], "y": src[1], "endX": dst[0], "endY": dst[1]})
            to = ({"strategy": dst_el.locator.strategy, "selector": dst_el.locator.value}
                  if dst_el and dst_el.locator else {"x": dst[0], "y": dst[1]})
            value = json.dumps({"to": to, "hold": hold}, ensure_ascii=False)
            if src_el:
                record(self.result, "drag", src_el, value=value)
            else:
                record_point(self.result, "drag", src[0], src[1], node_at(self.d.xml, *src), value=value)
            return f"Dragged from {src} to {dst} ({'press-and-hold' if hold else 'direct move'})."
        return await self._act(do)

    async def tap_point(self, x: int, y: int) -> str:
        return await self._point("tap", x, y)

    async def long_press_point(self, x: int, y: int) -> str:
        return await self._point("long_press", x, y)

    async def list_apps(self, filter: str | None = None) -> str:
        apps = [p for p in await self.nav.installed() if not filter or filter.lower() in p.lower()]
        self.result.actions.append(ActionRecord(tool="list_apps", selector=filter, result=f"{len(apps)} apps"))
        if not apps:
            return (f"No installed app package contains '{filter}'. Try another word, or press_key home and "
                    "look for the app by its visible name in the launcher.")
        return "Installed apps (packages): " + ", ".join(apps)

    async def open_app(self, package: str, restart: bool = False) -> str:
        async def do():
            cold = await self.nav.open(package, restart)
            self.result.actions.append(ActionRecord(tool="open_app", selector=package,
                                                    result="restarted" if cold else "ok"))
            msg = f"App {package} is in the foreground."
            if not package_matches_step(package, self.st.instruction):
                # O modelo pode abrir um package sem relação com a app pedida. Aviso (não recusa): há casos
                # legítimos sem relação textual entre o nome visível e o package.
                msg += ("\nCHECK: this package name has no obvious relation to the app named in the step. "
                        "Confirm it is the right app; installed apps: " + ", ".join(self.nav.apps or []))
            return msg
        return await self._act(do, requested_switch=True, opened=package)

    async def close_apps(self, packages: list[str] | None = None) -> str:
        """Fechar apps. Sem lista: as apps usadas neste teste + a app à frente (exceto o sistema e o ecrã
        inicial). Termina-as e volta ao ecrã inicial."""
        async def do():
            if packages:
                targets = list(dict.fromkeys(packages))
            else:
                used = set(self.nav.opened) | {a.selector for a in self.result.actions
                                               if a.tool == "app_switched" and a.selector}
                home = await self.nav.home()
                targets = sorted(p for p in used | (self.d.packages() - SYSTEM_PACKAGES)
                                 if p not in SYSTEM_PACKAGES and p != home
                                 and (home or not any(h in p for h in _LAUNCHER_HINTS)))
            closed = [p for p in targets if await self.nav.close(p)]
            self.nav.opened.difference_update(closed)  # reabrir depois = arranque a frio
            await self.d.key("home")
            self.result.actions.append(ActionRecord(tool="close_apps", selector=",".join(closed), result="ok"))
            return f"Closed {', '.join(closed) or 'no running app'}; the home screen is shown."
        return await self._act(do, requested_switch=True)

    async def get_screen(self, filter: str | None = None) -> str:
        return await self.d.screen_text(filter)

    async def request_human(self, instruction: str) -> str:
        # Interrompe o passo: o orquestrador pausa a execução (waiting_for_user) e repete o passo
        # depois de o QA continuar. As credenciais nunca passam pelo QAgent nem pelo LLM.
        raise HumanInputRequired(instruction)

    async def finish_step(self, status: str, reason: str) -> str:
        return "finished"  # tratado pelo ciclo (qagent.ai_executor) antes de chegar aqui

    def as_langchain(self) -> list[StructuredTool]:
        T = StructuredTool.from_function
        return [
            T(coroutine=self.tap, name="tap", args_schema=S.RefArgs, description="Tap an element."),
            T(coroutine=self.long_press, name="long_press", args_schema=S.RefArgs, description="Long-press an element."),
            T(coroutine=self.type_text, name="type_text", args_schema=S.TypeArgs,
              description="Replace the text of an editable field (optionally press Enter)."),
            T(coroutine=self.read_text, name="read_text", args_schema=S.RefArgs,
              description="Read an element's current text and state (fresh)."),
            T(coroutine=self.swipe, name="swipe", args_schema=S.SwipeArgs,
              description="Swipe gesture (horizontal pagers, dismissing, moving content)."),
            T(coroutine=self.scroll, name="scroll", args_schema=S.ScrollArgs,
              description="Scroll the screen or a container."),
            T(coroutine=self.scroll_to_text, name="scroll_to_text", args_schema=S.ScrollToArgs,
              description="Scroll until an element whose text/description contains the given text is visible."),
            T(coroutine=self.press_key, name="press_key", args_schema=S.KeyArgs,
              description="Press a device key (back, enter, …) or hide the keyboard."),
            T(coroutine=self.wait, name="wait", args_schema=S.WaitArgs, description="Wait a fixed time."),
            T(coroutine=self.wait_for_text, name="wait_for_text", args_schema=S.WaitTextArgs,
              description="Wait until a text appears (or disappears) on screen. Use to verify."),
            T(coroutine=self.look_at_screen, name="look_at_screen",
              description="Get a screenshot of the current screen (when the description is not enough)."),
            T(coroutine=self.tap_point, name="tap_point", args_schema=S.PointArgs,
              description="Tap a position of the latest screenshot. Only for content visible in look_at_screen "
                          "that is not listed in the screen description (drawn or not exposed UI)."),
            T(coroutine=self.long_press_point, name="long_press_point", args_schema=S.PointArgs,
              description="Long-press a position of the latest screenshot (same rule as tap_point)."),
            T(coroutine=self.drag, name="drag", args_schema=S.DragArgs,
              description="Drag from an element or screenshot position to another (move or reorder items, "
                          "sliders, drawing). Positions follow the tap_point rule."),
            T(coroutine=self.list_apps, name="list_apps", args_schema=S.ListAppsArgs,
              description="List installed apps (package names) to find an app mentioned by name."),
            T(coroutine=self.open_app, name="open_app", args_schema=S.OpenAppArgs,
              description="Open (or switch to) an installed app by package."),
            T(coroutine=self.close_apps, name="close_apps", args_schema=S.CloseAppsArgs,
              description="Close (force-stop) apps and go to the home screen. Use it when the test says to close "
                          "an app or all apps."),
            T(coroutine=self.get_screen, name="get_screen", args_schema=S.ScreenArgs,
              description="Describe the current screen again (optionally filtered)."),
            T(coroutine=self.request_human, name="request_human", args_schema=S.HumanArgs,
              description="Pause and ask the human tester to do something on the device (e.g. authenticate)."),
            T(coroutine=self.finish_step, name="finish_step", args_schema=S.FinishArgs,
              description="End the step with the verdict. Must be the last call."),
        ]
