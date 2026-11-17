"""Normalizador: Gherkin determinístico e texto livre com LLM simulado."""

import asyncio

from langchain_core.messages import AIMessage

from qagent.llm import LlmParams, build_llm
from qagent.models import GherkinScenario
from qagent.normalizer import from_free_text, from_gherkin


def test_gherkin_and_inherits_previous_type():
    sc = GherkinScenario(name="x", scenario=[
        {"type": "GIVEN", "description": "app aberta"},
        {"type": "WHEN", "description": "toco em Login"},
        {"type": "THEN", "description": "vejo Products"},
        {"type": "AND", "description": "vejo o carrinho"},
        {"type": "BUT", "description": "não vejo erro"}])
    steps = from_gherkin(sc)
    assert [s.action for s in steps] == ["ai"] * 5
    assert [s.text.split("]")[0] + "]" for s in steps] == ["[GIVEN]", "[WHEN]", "[THEN]", "[THEN]", "[THEN]"]
    assert steps[3].name == "And vejo o carrinho" and steps[4].name == "But não vejo erro"


def test_free_text_structured_output_with_fake_llm():
    reply = AIMessage(content="", tool_calls=[{"name": "NormalizedCase", "id": "n1", "args": {
        "name": "Login válido",
        "steps": [{"type": "GIVEN", "description": "a app está aberta no ecrã de login"},
                  {"type": "WHEN", "description": "faço login com {{testData.username}} e {{testData.password}}"},
                  {"type": "THEN", "description": "é apresentado o catálogo de produtos"}]}}],
        usage_metadata={"input_tokens": 300, "output_tokens": 80, "total_tokens": 380})
    llm = build_llm(LlmParams("fake", "scripted"), scripted=[reply])
    case, steps, tokens = asyncio.run(from_free_text("Faz login e valida o catálogo", llm, ["username", "password"]))
    assert case.name == "Login válido" and len(steps) == 3
    assert steps[1].text == "[WHEN] faço login com {{testData.username}} e {{testData.password}}"
    assert tokens == {"input": 300, "output": 80}
