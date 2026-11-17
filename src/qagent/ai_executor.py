"""Executor de um passo em linguagem natural com LLM. Agnóstico à app.

Desenho:
- ReAct limitado ao passo: o LLM recebe o passo, os placeholders de testData e o modelo do ecrã
  (qagent.screen: todos os elementos interativos, incluindo só-ícone, com estado e posição).
- O LLM refere elementos por `ref` (e1, e2…) do último ecrã; o QAgent converte-a no locator mais estável
  e regista-o (frágil se for resourceId+instance ou coordenadas). O LLM não escreve locators.
- Segredos: o LLM só vê `{{testData.<chave>}}`; o valor é substituído na execução.
- O veredicto (finish_step) é validado no código (qagent.agent.verdict).

Aqui fica só o ciclo ReAct; as restantes partes estão em qagent.agent.
"""

from __future__ import annotations

import asyncio  # noqa: F401 — os testes substituem asyncio.sleep através deste módulo

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from qagent.agent.device import ANDROID_KEYCODES, Device, SessionView  # noqa: F401 — compatibilidade
from qagent.agent.errors import HumanInputRequired, PreexistingState  # noqa: F401 — API pública
from qagent.agent.navigation import AppNavigator
from qagent.agent.recording import Secrets
from qagent.agent.schemas import FinishArgs
from qagent.agent.state import StepState
from qagent.agent.tools import FREE_TOOLS, REPEATABLE_TOOLS, StepTools
from qagent.agent.transcript import (MAX_TOOL_OUTPUT, compact_old_screens, data_description, has_screen,
                                     image_message, step_message)
from qagent.agent.verdict import VerdictJudge
from qagent.appium_session import AppiumSession
from qagent.executor import StepFailed, StructuredExecutor
from qagent.mcp_client import McpConnection
from qagent.models import StepResult
from qagent.prompts import DEFAULT_EXECUTOR, EXECUTOR_PROMPTS, executor_prompt

SYSTEM_PROMPT = EXECUTOR_PROMPTS[DEFAULT_EXECUTOR]  # compatibilidade; os prompts vivem em prompts.py


class AiStepExecutor:
    def __init__(self, conn: McpConnection, session_id: str, structured: StructuredExecutor,
                 llm: BaseChatModel, test_data: dict[str, str], secret_keys: set[str],
                 max_actions: int = 8, session: AppiumSession | None = None, udid: str | None = None,
                 report_language: str = "European Portuguese (pt-PT)", prompt_version: str | None = None) -> None:
        self._exec = structured
        self._llm = llm
        self._max_actions = max_actions
        self._secrets = Secrets(test_data, secret_keys)
        # Estado por execução (partilhado entre passos): último ecrã, apps instaladas e apps já abertas.
        self._device = Device(conn, session_id, session or SessionView(conn, session_id))
        self._nav = AppNavigator(conn, session_id, udid)
        self.prompt_version, self._system_prompt = executor_prompt(prompt_version, report_language)
        self.llm_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0

    def _track_usage(self, ai: AIMessage) -> None:
        self.llm_calls += 1
        u = getattr(ai, "usage_metadata", None) or {}
        self.tokens_in += int(u.get("input_tokens", 0))
        self.tokens_out += int(u.get("output_tokens", 0))

    async def run_instruction(self, instruction: str, result: StepResult,
                              history: list[tuple[int, str, str, str]] | None = None,
                              tester_acted: bool = False) -> None:
        """Preenche result. Levanta StepFailed (falha funcional) ou RuntimeError/ToolError (erro)."""
        st = StepState.for_instruction(instruction)
        tools = StepTools(self._device, self._nav, self._secrets, st, result).as_langchain()
        judge = VerdictJudge(self._device, st, result)
        by_name = {t.name: t for t in tools}
        llm = self._llm.bind_tools(tools)
        history = history or []
        tokens0 = (self.tokens_in, self.tokens_out)
        messages = [
            SystemMessage(self._system_prompt),
            step_message(instruction, history, data_description(self._secrets.data, self._secrets.keys),
                         await self._device.screen_text()),
        ]
        actions, nudged, calls_seen, budget_out = 0, False, {}, False
        try:
            for _ in range(self._max_actions + 8):  # margem para observações, veredicto final e finish_step
                ai: AIMessage = await llm.ainvoke(messages)
                self._track_usage(ai)
                messages.append(ai)
                if not ai.tool_calls:
                    if nudged:
                        raise RuntimeError(f"LLM não chamou ferramentas: {str(ai.content)[:200]}")
                    nudged = True
                    messages.append(HumanMessage("Use the tools. End with finish_step."))
                    continue
                skip_rest = False
                for tc in ai.tool_calls:
                    name, args = tc["name"], tc.get("args", {})
                    if skip_rest:
                        messages.append(ToolMessage("Skipped.", tool_call_id=tc["id"]))  # OpenAI exige resposta
                        continue
                    if name == "finish_step":
                        verdict = FinishArgs(**args)
                        if budget_out:  # veredicto forçado: não contestar (evita ciclos sem orçamento)
                            st.when_fail_challenged = st.then_fail_challenged = st.preexisting_challenged = True
                        problem = await judge.validate(verdict, history, tester_acted)
                        if problem:
                            messages.append(ToolMessage(problem, tool_call_id=tc["id"]))
                            skip_rest = True
                            continue
                        result.reason = verdict.reason
                        if verdict.status == "failed":
                            raise StepFailed(verdict.reason)
                        return
                    if name not in by_name:
                        out = f"ERROR: unknown tool '{name}'"
                    else:
                        sig = (name, tuple(sorted((k, str(v)) for k, v in args.items())))
                        calls_seen[sig] = calls_seen.get(sig, 0) + 1
                        if calls_seen[sig] > 2 and name not in REPEATABLE_TOOLS:
                            out = "REJECTED: you already made this exact call twice. Try something different."
                        elif budget_out and name not in FREE_TOOLS:
                            out = "REJECTED: the action budget is exhausted. Call finish_step now."
                        else:
                            if name not in FREE_TOOLS:
                                actions += 1
                            if name not in FREE_TOOLS and actions > self._max_actions:
                                # Orçamento esgotado: numa verificação, "procurei e não encontrei" é um
                                # resultado (failed com o observado), não um erro de infraestrutura.
                                budget_out = True
                                out = (f"REJECTED: action budget exhausted ({self._max_actions} actions). Do not "
                                       "act any more: call finish_step now with your verdict based on what you "
                                       "observed (failed, quoting what you saw, if the expected result was not "
                                       "found).")
                            else:
                                out = await by_name[name].ainvoke(args)
                    out = str(out)[:MAX_TOOL_OUTPUT]
                    if has_screen(out):
                        compact_old_screens(messages)  # só o ecrã mais recente fica completo
                    messages.append(ToolMessage(out, tool_call_id=tc["id"]))
                if st.pending_image:
                    messages.append(image_message(st.pending_image))
                    st.pending_image = None
            if budget_out:
                raise RuntimeError(f"maxActionsPerStep ({self._max_actions}) excedido e sem veredicto do LLM")
            raise RuntimeError("limite de iterações do LLM atingido sem finish_step")
        finally:
            result.tokens = {"input": self.tokens_in - tokens0[0], "output": self.tokens_out - tokens0[1]}
