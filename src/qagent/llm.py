"""Fábrica de LLM agnóstica ao provider (CPS 6.2, 7.9): escolhida pelos cabeçalhos X-Provider / X-LLM-*.

Providers: gemini (ponte, F2), azure (alvo), fake (testes da "canalização" sem quota).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

Provider = Literal["gemini", "azure", "fake"]
# Azure: sem valores por omissão — endpoint, deployment e versão são sempre indicados pelo utilizador.
DEFAULT_MODELS: dict[str, str] = {"gemini": "gemini-2.5-flash", "fake": "scripted"}
PROVIDERS = ("gemini", "azure", "fake")


class LlmConfigError(ValueError):
    pass


@dataclass(frozen=True)
class LlmParams:
    provider: Provider
    model: str
    api_key: str | None = None
    endpoint: str | None = None
    api_version: str | None = None

    def describe(self) -> dict:
        """Para logs/relatório: nunca inclui a chave."""
        return {"provider": self.provider, "model": self.model, "endpoint": self.endpoint}


def params_from_headers(provider: str | None, model: str | None, api_key: str | None,
                        endpoint: str | None, api_version: str | None) -> LlmParams | None:
    if not provider or provider == "none":
        return None
    provider = provider.lower()
    if provider not in PROVIDERS:
        raise LlmConfigError(f"X-Provider '{provider}' não suportado (use: gemini, azure)")
    if provider != "fake" and not api_key:
        raise LlmConfigError("X-LLM-API-Key em falta")
    if provider == "azure":
        missing = [h for h, v in (("X-LLM-Endpoint", endpoint), ("X-LLM-Model", model),
                                  ("X-LLM-APIVersion", api_version)) if not v]
        if missing:
            raise LlmConfigError(f"Azure OpenAI: em falta {', '.join(missing)}")
        return LlmParams(provider, model, api_key, endpoint, api_version)
    return LlmParams(provider, model or DEFAULT_MODELS[provider], api_key, endpoint, api_version)


def build_llm(p: LlmParams, *, scripted: list[AIMessage] | None = None) -> BaseChatModel:
    if p.provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        # max_retries cobre 429 (quota por minuto do free tier) com backoff do SDK.
        return ChatGoogleGenerativeAI(model=p.model, google_api_key=p.api_key, temperature=0,
                                      max_retries=4, timeout=90)
    if p.provider == "azure":
        from langchain_openai import AzureChatOpenAI
        kwargs: dict[str, Any] = {}
        # Modelos de raciocínio (gpt-5*, o1/o3/o4) só aceitam a temperatura por omissão → não enviar.
        if not is_reasoning_model(p.model):
            kwargs["temperature"] = 0
        return AzureChatOpenAI(azure_deployment=p.model, api_key=p.api_key, azure_endpoint=p.endpoint,
                               api_version=p.api_version,
                               max_retries=4, timeout=120, **kwargs)
    return ScriptedChatModel(responses=list(scripted or []))


def is_reasoning_model(deployment: str) -> bool:
    """Heurística pelo nome do deployment (ex.: 'gpt-5-mini-prod'). Deployments com nomes livres que
    escondam o modelo não são detetados — nesse caso o Azure devolve 400 'temperature' e é preciso
    renomear ou ajustar aqui."""
    name = deployment.lower()
    return name.startswith(("gpt-5", "o1", "o3", "o4")) or "-gpt-5" in name


class ScriptedChatModel(BaseChatModel):
    """LLM simulado: devolve respostas programadas (com tool_calls). Para testar o ciclo sem quota."""

    responses: list[AIMessage]
    i: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None,
                  **kwargs: Any) -> ChatResult:
        if self.i >= len(self.responses):
            msg = AIMessage(content="", tool_calls=[{
                "name": "finish_step", "args": {"status": "failed", "reason": "script esgotado"},
                "id": f"call-end-{self.i}"}])
        else:
            msg = self.responses[self.i]
        self.i += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])
