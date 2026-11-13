# F1 — Registo: cliente MCP mínimo em Python

> Referência: `Prompts/CPS-QAgent.md`, secção 8 (F1). Entrada: `docs/F0-registo.md`, secção 4.

## 1. Resultado (2026-11-11): **PASSOU → CONTINUAR**

**Critério do CPS:** 10 ciclos create→screenshot→delete sem sessões órfãs; sessão MCP única por execução; dependências sem conflitos.

| Critério | Resultado | Evidência |
|---|---|---|
| 10 ciclos sem órfãs | ✅ **10/10**; `list` numa ligação MCP nova no fim → "No active sessions found." | `runs/f1/20261111-195423/result.json` |
| Sessão MCP única por execução | ✅ 10 `mcp-session-id` distintos (1 por ciclo); o id é o mesmo no início e no fim de cada ciclo | `checks.mcp_session_id_stable` |
| Tools LangChain usam a mesma sessão | ✅ `load_mcp_tools(session)` → a tool `appium_session_management` vê a sessão Appium criada pelo orquestrador | `checks.adapter_reuses_session` |
| Dependências sem conflitos | ✅ com ajuste (ver 3) | `pyproject.toml` |

Verificações por ciclo (todas `true` em 10/10): nenhuma sessão antes, adapter reutiliza a sessão, app em primeiro plano (sem diálogo de sistema), ficheiro de screenshot válido, nenhuma sessão depois do `delete`, `mcp-session-id` estável.

Execuções extra: 3/3 com `noReset=true` (`runs/f1/20261111-195652`). 0 ANRs no logcat durante a F1.

## 2. O que foi construído

| Ficheiro | Papel |
|---|---|
| `pyproject.toml` | Projeto `uv`, Python 3.11, dependências fixas |
| `src/qagent/config.py` | `Settings` (pydantic-settings, prefixo `QAGENT_`, `.env` carregado explicitamente) |
| `src/qagent/mcp_client.py` | `McpConnection`: 1 transporte + 1 `ClientSession` por execução (HTTP ou stdio), registo de chamadas com duração, `ToolError` em `isError`, `langchain_tools()` filtradas pela *allowlist* do LLM |
| `src/qagent/appium_session.py` | `AppiumSession`: `select_device` → `create` determinístico, `delete`, `list`, `screenshot`, `foreground_packages()` (deteção de diálogos de sistema) |
| `scripts/f1_lifecycle.py` | Executa N ciclos e grava `runs/f1/<timestamp>/result.json` + screenshots |

Executar: `uv run python scripts/f1_lifecycle.py --cycles 10 [--no-reset]` (o appium-mcp tem de estar a correr: `scripts/start-appium-mcp.ps1`).

## 3. Dependências (Anexo A, ponto 14 → respondido)

| Pacote | Versão | Nota |
|---|---|---|
| langchain-core | **0.3.46** | igual ao genai_fastapi |
| langchain-openai / langchain-google-genai | 0.3.1 / 2.1.0 | iguais ao genai_fastapi; imports OK |
| langgraph | 0.5.4 | |
| langchain-mcp-adapters | **0.1.14** | ⚠️ ver abaixo |
| mcp | 1.30.0 (`<2`) | |

- **Armadilha 1:** `langchain-mcp-adapters` 0.2.0 declara `langchain-core>=0.3.36`, mas importa `langchain_core.messages.content`, que não existe no 0.3.46 → `ModuleNotFoundError`. O resolver aceita a combinação; só falha em *runtime*. **0.1.14 é a última versão compatível** (0.1.7–0.1.14 testadas).
- **Armadilha 2:** sem teto, o resolver escolhe `mcp` 2.x (major nova, não validada) → fixado `mcp<2`.
- **Consequência:** manter o core 0.3.46 prende o QAgent ao adapters 0.1.x. Para atualizar os adapters é preciso subir para o `langchain-core` 1.x, o que diverge do genai_fastapi. Decidir na F7 (integração).

## 4. Tempos (10 ciclos, transporte HTTP, `noReset=false`)

| Etapa | mín | mediana | máx |
|---|---|---|---|
| Ligar MCP (initialize + list_tools) | 388 ms | 403 ms | 532 ms |
| `select_device` + `create` | 9,0 s | **10,0 s** | 11,5 s |
| Page source (XML completo, ≈ 33 KB) | 539 ms | 614 ms | 1,2 s |
| Screenshot | 213 ms | 233 ms | 265 ms |
| `delete` | 1,8 s | 2,2 s | 2,4 s |
| **Ciclo total** | 12,3 s | **13,6 s** | 15,2 s |

- Na F0, o `create` demorou ≈ 51 s porque incluiu a primeira instalação dos servidores UiAutomator2. Com tudo instalado: ≈ 10 s com `noReset=false` e ≈ 7,5 s com `noReset=true` (do 2.º ciclo em diante).
- Com o servidor HTTP de longa duração, ligar ao MCP custa ≈ 0,4 s, contra ≈ 33 s do stdio na F0. Confirma o ajuste 4.3.1 do registo da F0.
- 7 chamadas MCP por ciclo.

## 5. Comportamentos do appium-mcp descobertos na F1

1. **As sessões Appium são globais ao processo appium-mcp.** Uma 2.ª ligação MCP vê a sessão de outra ligação no `list`, e até como "(active)". **Risco:** com o servidor partilhado, uma chamada sem `sessionId` explícito pode atuar sobre a sessão de outra execução (ou de outro cliente MCP ligado ao mesmo servidor).
   → **Regra para a F2/F3:** passar sempre `sessionId` explícito nas ferramentas que o aceitam, e manter **uma execução de cada vez por servidor** (*lock* por UDID, CPS 7.3 regra 5) enquanto se usar transporte HTTP.
2. **A limpeza ao desligar (`APPIUM_MCP_ON_CLIENT_DISCONNECT=delete_all`) só abrange as sessões que a própria ligação criou** (`ownership=owned`). Testado: (a) ligação A sai sem `delete` → sessão apagada e *port forwards* do adb removidos; (b) ligação B liga e desliga com A ativa → a sessão de A continua viva. Isto dá uma rede de segurança para *crash*/*stop* sem afetar outras execuções.
3. **`appium_get_page_source` devolve o XML embrulhado em markdown** (`Page source retrieved successfully: ```xml <?xml…</hierarchy>````). É preciso extrair entre o primeiro `<` e o último `>`.
4. **O endpoint `/sse` envia um evento SSE legado `endpoint`.** O cliente `mcp` 1.30 escreve `Unknown SSE event: endpoint` no stderr; é inofensivo (ruído de log).
5. **`SCREENSHOTS_DIR` é global no servidor HTTP** (definido no arranque, hoje `runs/f0/screenshots`). Não há pastas por execução como previa o CPS 7.7 para stdio. Solução atual: o QAgent copia o PNG para `runs/<execução>/screenshots/`. Sugestão: mudar o `start-appium-mcp.ps1` para uma pasta neutra (ex.: `runs/_mcp-server/`).

## 6. Pontos do Anexo A respondidos na F1

| # | Ponto | Resposta |
|---|---|---|
| 6 | Persistência da sessão MCP no adaptador Python | ✅ `load_mcp_tools(session)` reutiliza a `ClientSession` passada; `mcp-session-id` estável durante a execução |
| 14 | `langchain-core` 0.3.46 vs adapters/langgraph | ✅ compatível com adapters **0.1.14** + langgraph 0.5.4 (ver 3) |

## 7. Próximo passo

Pela sequência revista do CPS: **F4** (API FastAPI) e **F4b** (frontend) com LLM simulado e passos estruturados. A F2 (executor de passo com LLM) fica à espera de um LLM com API (Gemini *free tier*, Ollama ou Azure OpenAI).
