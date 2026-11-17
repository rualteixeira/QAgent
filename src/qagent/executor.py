"""Executores de passo.

- StructuredExecutor: passos determinísticos (sem LLM). Usa sempre `sessionId` explícito,
  porque as sessões Appium são globais no servidor appium-mcp.
- O executor com LLM implementa o mesmo protocolo `StepExecutor`.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Protocol

from qagent.mcp_client import McpConnection, ToolError
from qagent.models import ActionRecord, LocatorRecord, StepResult, StructuredStep

_ELEMENT_ID_RE = re.compile(r"elementId '([^']+)'")
_GOT_TEXT_RE = re.compile(r"got text (.*) from element \S+?\.?\s*$", re.DOTALL)
_TEMPLATE_RE = re.compile(r"\{\{\s*testData\.([A-Za-z0-9_]+)\s*\}\}")


class StepFailed(Exception):
    """Falha funcional (o passo não se verificou) → status `failed`."""


class StepExecutor(Protocol):
    async def run(self, step: StructuredStep, result: StepResult) -> None:
        """Executa o passo e preenche result.actions/locators/reason.
        Levanta StepFailed (falha funcional) ou outra exceção (erro de infraestrutura)."""


def render(text: str, test_data: dict[str, str]) -> str:
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in test_data:
            raise StepFailed(f"testData.{key} não definido")
        return test_data[key]
    return _TEMPLATE_RE.sub(sub, text)


class StructuredExecutor:
    POLL_S = 0.5

    def __init__(self, conn: McpConnection, session_id: str, test_data: dict[str, str]) -> None:
        self._conn = conn
        self._sid = session_id
        self._data = test_data

    async def _call(self, result: StepResult, tool: str, args: dict, *, loc=None) -> str:
        args = {**args, "sessionId": self._sid}
        try:
            res = await self._conn.call(tool, args)
        except ToolError as e:
            result.actions.append(ActionRecord(
                tool=tool, strategy=loc.strategy if loc else None,
                selector=loc.value if loc else None, result=f"error: {str(e)[:200]}"))
            raise
        result.actions.append(ActionRecord(
            tool=tool, strategy=loc.strategy if loc else None,
            selector=loc.value if loc else None, result="ok"))
        return res.text

    async def _find(self, step: StructuredStep, result: StepResult) -> str:
        """Procura com espera ativa até timeoutSec (o UiAutomator2 não tem implicit wait)."""
        loc = step.locator
        deadline = time.monotonic() + step.timeout_sec
        attempts = 0
        while True:
            attempts += 1
            try:
                res = await self._conn.call("appium_find_element", {
                    "strategy": loc.strategy, "selector": loc.value, "sessionId": self._sid})
            except ToolError as e:
                if time.monotonic() >= deadline:
                    result.actions.append(ActionRecord(
                        tool="appium_find_element", strategy=loc.strategy, selector=loc.value,
                        result=f"not found after {attempts} attempt(s) / {step.timeout_sec:g}s"))
                    raise StepFailed(
                        f"Elemento não encontrado em {step.timeout_sec:g}s "
                        f"({loc.strategy} = {loc.value!r}).") from e
                await asyncio.sleep(self.POLL_S)
                continue
            m = _ELEMENT_ID_RE.search(res.text)
            if not m:
                raise ToolError(f"elementId não encontrado na resposta: {res.text[:200]}")
            result.actions.append(ActionRecord(
                tool="appium_find_element", strategy=loc.strategy, selector=loc.value,
                result="ok" if attempts == 1 else f"ok after {attempts} attempts"))
            self._record_locator(step, result)
            return m.group(1)

    @staticmethod
    def _record_locator(step: StructuredStep, result: StepResult) -> None:
        loc = step.locator
        if not any(l.strategy == loc.strategy and l.value == loc.value for l in result.locators):
            result.locators.append(LocatorRecord(
                strategy=loc.strategy, value=loc.value, fragile=loc.strategy == "xpath"))

    async def run(self, step: StructuredStep, result: StepResult) -> None:
        loc = step.locator
        match step.action:
            case "tap":
                el = await self._find(step, result)
                await self._call(result, "appium_gesture", {"action": "tap", "elementUUID": el}, loc=loc)
                result.reason = f"Tocado ({loc.strategy} = {loc.value!r})."
            case "type":
                el = await self._find(step, result)
                value = render(step.text, self._data)
                await self._call(result, "appium_set_value", {"elementUUID": el, "text": value}, loc=loc)
                shown = "***" if value != step.text else repr(value)
                result.reason = f"Texto {shown} introduzido ({loc.strategy} = {loc.value!r})."
            case "scroll_to":
                # 2 tentativas: logo após uma transição (ex.: menu a abrir) o appium-mcp vê
                # "page source did not change" e desiste.
                for attempt in (1, 2):
                    try:
                        await self._call(result, "appium_gesture", {
                            "action": "scroll_to_element", "strategy": loc.strategy,
                            "selector": loc.value}, loc=loc)
                        break
                    except ToolError as e:
                        if attempt == 2:
                            raise StepFailed(f"Elemento não encontrado após scroll ({loc.value!r}).") from e
                        await asyncio.sleep(1.0)
                self._record_locator(step, result)
                result.reason = f"Elemento visível após scroll ({loc.strategy} = {loc.value!r})."
            case "assert_visible":
                await self._find(step, result)
                result.reason = f"Elemento presente ({loc.strategy} = {loc.value!r})."
            case "assert_text":
                el = await self._find(step, result)
                text = await self._call(result, "appium_get_text", {"elementUUID": el}, loc=loc)
                m = _GOT_TEXT_RE.search(text)
                actual = m.group(1) if m else text
                expected = render(step.text, self._data)
                ok = expected in actual if step.contains else actual == expected
                verb = "contém" if step.contains else "="
                if not ok:
                    raise StepFailed(f"Texto observado {actual!r}; esperado {verb} {expected!r}.")
                result.reason = f"Texto observado {actual!r} ({verb} esperado)."
            case "back":
                await self._call(result, "appium_gesture", {"action": "back"})
                result.reason = "Navegação 'back' executada."
            case "wait":
                await asyncio.sleep(step.timeout_sec)
                result.reason = f"Espera de {step.timeout_sec:g}s."
