"""F3 — normalizador de entrada (CPS 7.1): texto livre / Gherkin → passos `ai`.

- Gherkin (`scenario`): determinístico, sem LLM (CPS 7.4: "se vier scenario, não se usa o LLM").
- Texto livre (`testExecution`): 1 chamada LLM com saída estruturada (Pydantic).
Cada passo leva o tipo Gherkin no texto ("[THEN] …") para o executor distinguir ação de verificação.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from qagent.models import GherkinScenario, StructuredStep
from qagent.prompts import DEFAULT_NORMALIZER, NORMALIZER_PROMPTS, normalizer_prompt

StepType = Literal["GIVEN", "WHEN", "THEN", "AND", "BUT"]
MAX_STEPS = 15


class NormalizedStep(BaseModel):
    type: StepType = Field(description="GIVEN = precondition, WHEN = action, THEN = verification of the expected result")
    description: str = Field(description="One atomic, executable step, in the language of the test case")


class NormalizedCase(BaseModel):
    name: str = Field(description="Short test case name")
    steps: list[NormalizedStep] = Field(min_length=1, max_length=MAX_STEPS)


NORMALIZER_PROMPT = NORMALIZER_PROMPTS[DEFAULT_NORMALIZER]  # compatibilidade; ver prompts.py


def _ai_step(step_type: str, description: str) -> StructuredStep:
    kind = "AND" if step_type == "BUT" else step_type
    return StructuredStep(name=f"{step_type.title()} {description}", action="ai",
                          text=f"[{kind}] {description}")


def from_gherkin(scenario: GherkinScenario) -> list[StructuredStep]:
    """AND/BUT herdam o significado do passo anterior: mantém-se o tipo para o nome, e o texto
    recebe o tipo efetivo (ação vs. verificação) para o executor."""
    steps, last = [], "GIVEN"
    for g in scenario.scenario:
        effective = last if g.type in ("AND", "BUT") else g.type
        last = effective
        s = _ai_step(g.type, g.description)
        s.text = f"[{effective}] {g.description}"
        steps.append(s)
    return steps


async def from_free_text(text: str, llm: BaseChatModel, placeholders: list[str]) -> tuple[
        NormalizedCase, list[StructuredStep], dict[str, int]]:
    """Devolve (caso normalizado, passos, tokens). Lança ValueError se a saída for inválida."""
    structured = llm.with_structured_output(NormalizedCase, include_raw=True)
    data = "\n".join(f"- {{{{testData.{k}}}}}" for k in placeholders) or "(none)"
    out = await structured.ainvoke([
        SystemMessage(normalizer_prompt()[1]),
        HumanMessage(f"Available test data placeholders:\n{data}\n\nTest case:\n{text}"),
    ])
    raw = out.get("raw")
    usage = (getattr(raw, "usage_metadata", None) or {}) if raw is not None else {}
    tokens = {"input": int(usage.get("input_tokens", 0)), "output": int(usage.get("output_tokens", 0))}
    case: NormalizedCase | None = out.get("parsed")
    if case is None:
        raise ValueError(f"saída do normalizador inválida: {out.get('parsing_error')}")
    scenario = GherkinScenario(name=case.name, scenario=[
        {"type": s.type, "description": s.description} for s in case.steps])
    return case, from_gherkin(scenario), tokens
