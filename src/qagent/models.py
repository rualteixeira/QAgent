"""Contrato da API: modelos de entrada e de saída."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---------- Entrada ----------

class GherkinStep(_Camel):
    type: Literal["GIVEN", "WHEN", "THEN", "AND", "BUT"]
    description: str


class GherkinScenario(_Camel):
    name: str
    scenario: list[GherkinStep]


class Locator(_Camel):
    strategy: Literal["accessibility id", "id", "-android uiautomator", "-ios predicate string",
                      "-ios class chain", "xpath"]
    value: str


StepAction = Literal["tap", "type", "scroll_to", "assert_visible", "assert_text", "back", "wait", "ai", "manual"]


class StructuredStep(_Camel):
    """Passo determinístico (sem LLM).

    - tap / scroll_to / assert_visible: `locator`
    - type: `locator` + `text` (aceita `{{testData.<chave>}}`)
    - assert_text: `locator` + `text` (igualdade; `contains=true` para substring)
    - back: sem campos; wait: `timeoutSec` = segundos de espera
    - ai: `text` = instrução em linguagem natural, executada pelo LLM (cabeçalhos X-Provider/X-LLM-*)
    """
    name: str | None = None
    action: StepAction
    locator: Locator | None = None
    text: str | None = None
    contains: bool = False
    timeout_sec: float = Field(10, gt=0, le=120)

    @model_validator(mode="after")
    def _check_fields(self) -> "StructuredStep":
        if self.action in ("tap", "type", "scroll_to", "assert_visible", "assert_text") and not self.locator:
            raise ValueError(f"a ação '{self.action}' exige 'locator'")
        if self.action in ("type", "assert_text") and self.text is None:
            raise ValueError(f"a ação '{self.action}' exige 'text'")
        if self.action in ("ai", "manual") and not (self.text and self.text.strip()):
            raise ValueError(f"a ação '{self.action}' exige 'text' (a instrução em linguagem natural)")
        return self


class AndroidApp(_Camel):
    app_package: str | None = None
    app_activity: str | None = None
    app: str | None = None


class IosApp(_Camel):
    bundle_id: str | None = None
    app: str | None = None


class AppSpec(_Camel):
    android: AndroidApp | None = None
    ios: IosApp | None = None


class DeviceSpec(_Camel):
    udid: str | None = None
    type: Literal["EMULATOR", "REAL"] = "EMULATOR"
    remote_server_url: str | None = None


class Options(_Camel):
    stop_on_failure: bool = True
    screenshots: Literal["every_step", "on_failure", "none"] = "every_step"
    max_actions_per_step: int = Field(8, ge=1, le=50)
    timeout_per_step_sec: float = Field(90, gt=0, le=600)
    record_video: bool = False
    # Apps cujos dados são apagados no início (estado limpo e repetível). Explícito: nunca automático.
    reset_apps: list[str] = Field(default_factory=list, max_length=20)
    # Tempo máximo à espera de uma ação do QA (ex.: autenticação manual). Não conta para timeoutPerStepSec.
    human_timeout_sec: float = Field(600, ge=30, le=3600)
    # Idioma dos motivos/instruções gerados pelo LLM (os resumos do QAgent são em português).
    report_language: str = Field("European Portuguese (pt-PT)", max_length=60)
    # Versão do prompt do executor (A/B e reprodutibilidade); omissão: prompts.DEFAULT_EXECUTOR.
    prompt_version: Literal["e1", "e2", "e3"] | None = None
    # Novas tentativas só para falhas de infraestrutura antes dos passos (ligação ao appium-mcp, criação
    # da sessão). Nunca se repete um passo: as ações não são idempotentes e uma falha da app não se "corrige".
    infra_retries: int = Field(1, ge=0, le=3)

    @model_validator(mode="after")
    def _check_packages(self) -> "Options":
        import re
        bad = [p for p in self.reset_apps if not re.fullmatch(r"[A-Za-z][\w]*(\.[A-Za-z_][\w]*)+", p)]
        if bad:
            raise ValueError(f"resetApps: packages inválidos {bad}")
        return self


class TestExecutionInput(_Camel):
    test_execution: str | None = None
    scenario: GherkinScenario | None = None
    steps: list[StructuredStep] | None = Field(None, min_length=1)
    platform: Literal["android", "ios"] = "android"
    app: AppSpec | None = None
    device: DeviceSpec = Field(default_factory=DeviceSpec)
    # Valores literais ou "{{secret:<nome>}}" → variável de ambiente QAGENT_SECRET_<NOME>.
    test_data: dict[str, str] = Field(default_factory=dict)
    options: Options = Field(default_factory=Options)

    @model_validator(mode="after")
    def _need_input(self) -> "TestExecutionInput":
        if not (self.test_execution or self.scenario or self.steps):
            raise ValueError("indique 'testExecution', 'scenario' ou 'steps'")
        return self


# ---------- Saída ----------

StepStatus = Literal["pending", "running", "passed", "failed", "skipped", "error"]
# Classificação das falhas. app = a app não fez o esperado; environment = dispositivo/estado/humano;
# llm = provider ou executor LLM; appium_mcp = automação (appium-mcp/Appium).
FailureCategory = Literal["app", "environment", "llm", "appium_mcp"]
# Força da evidência do veredicto de um passo (aditivo ao status).
# verified = confirmado por uma verificação da máquina num ecrã relido (asserção, espera por texto, passo assert_*);
# executed = a ação foi feita, mas o resultado não foi verificado pela máquina (fica para um THEN seguinte);
# inconclusive = o veredicto assenta só no juízo do LLM, ou o passo terminou em erro (nada se concluiu sobre a app).
StepOutcome = Literal["verified", "executed", "inconclusive"]
ExecutionStatus = Literal["queued", "running", "waiting_for_user", "passed", "failed", "error", "cancelled"]
TERMINAL: frozenset[str] = frozenset({"passed", "failed", "error", "cancelled"})


class ElementSignature(_Camel):
    """Elemento tocado por coordenadas (sem locator estável): o script gerado confirma, antes de tocar, que o
    mesmo elemento está nesse ponto — senão falha ("ecrã diferente da gravação") em vez de tocar às cegas."""
    cls: str
    bounds: list[int] = Field(min_length=4, max_length=4)
    text: str | None = None   # só textos estáveis (sem dígitos, campo não editável)
    desc: str | None = None


class ActionRecord(_Camel):
    tool: str
    strategy: str | None = None
    selector: str | None = None
    result: str
    # Para gerar código: texto escrito como template (com {{testData.x}}, nunca o valor de um segredo),
    # texto observado numa leitura (mascarado), duração de esperas, etc.
    value: str | None = None
    # Só em ações por coordenadas: o elemento que estava nesse ponto na execução original.
    target: ElementSignature | None = None


class LocatorRecord(_Camel):
    strategy: str
    value: str
    element: str | None = None
    fragile: bool = False


class Evidence(_Camel):
    screenshot: str | None = None
    page_source: str | None = None


class StepResult(_Camel):
    id: int
    name: str
    status: StepStatus = "pending"
    reason: str | None = None
    actions: list[ActionRecord] = Field(default_factory=list)
    locators: list[LocatorRecord] = Field(default_factory=list)
    evidence: Evidence = Field(default_factory=Evidence)
    duration_ms: int | None = None
    tokens: dict[str, int] | None = None
    failure_category: FailureCategory | None = None
    outcome: StepOutcome | None = None


class DeviceInfo(_Camel):
    udid: str | None = None
    platform_version: str | None = None
    model: str | None = None
    home_package: str | None = None  # ecrã inicial (launcher) do dispositivo, perguntado ao Android
    mode: Literal["embedded", "remote"] = "embedded"


class Metrics(_Camel):
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tool_calls: int = 0
    infra_retries: int = 0


class Progress(_Camel):
    current_step: int = 0
    total_steps: int = 0
    message: str = ""
    # Preenchido enquanto status == waiting_for_user: o que o QA tem de fazer no dispositivo.
    awaiting_user: str | None = None
    awaiting_since: str | None = None


class ExecutionResult(_Camel):
    execution_id: str
    record_id: str
    status: ExecutionStatus = "queued"
    platform: str = "android"
    mode: Literal["structured", "llm"] = "structured"
    device: DeviceInfo = Field(default_factory=DeviceInfo)
    failure_category: FailureCategory | None = None
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    # Versão (versionName) de cada app usada no teste, lida no dispositivo — para reproduzir/triar falhas.
    app_versions: dict[str, str] = Field(default_factory=dict)
    # Contagem dos passos por outcome (verified/executed/inconclusive).
    outcomes: dict[str, int] = Field(default_factory=dict)
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    summary: str = ""
    progress: Progress = Field(default_factory=Progress)
    steps: list[StepResult] = Field(default_factory=list)
    metrics: Metrics = Field(default_factory=Metrics)
    artifacts: list[str] = Field(default_factory=list)


class ExecutionCreated(_Camel):
    execution_id: str
    status: ExecutionStatus


class ExecutionListItem(_Camel):
    execution_id: str
    status: ExecutionStatus
    created_at: str
    progress: Progress
    summary: str
