# F4 — Registo: API FastAPI

> Referência: `Prompts/CPS-QAgent.md`, secções 7.4, 7.5, 7.9, 8 (F4) e 9.3. Entradas: `docs/F0-registo.md`, `docs/F1-registo.md`.

## 1. Resultado (2026-11-11): **PASSOU (modo estruturado) → CONTINUAR**

**Critério do CPS:** CA1–CA4 e CA9 cumpridos via API.

**Ajuste de âmbito:** sem LLM com API, a F4 executa **passos estruturados determinísticos** (`steps`: ação + locator), o modo "sem LLM" previsto no CPS (6.2). Os pedidos só com `testExecution` (texto livre) ou `scenario` (Gherkin) respondem **501**. A versão em linguagem natural do CA2/CA3 fica para a F2/F3. O executor estruturado implementa o mesmo protocolo (`StepExecutor`) que o executor com LLM vai implementar.

| CA | Resultado | Evidência |
|---|---|---|
| **CA1** `/health` + ferramentas | ✅ `status=ok`: Node v24.15.0, adb com `emulator-5554`, appium-mcp **1.99.3** (= versão fixada), 32 ferramentas, nenhuma da *allowlist* em falta. ⚠️ Transporte **HTTP** em vez de stdio (decisão F0-registo 4.3) | `GET /health` |
| **CA2** login positivo | ✅ (estruturado) `passed`, **9/9 passos**, 33 s. Cada passo tem `status`, `reason`, screenshot e locators | `runs/8c4baf87c713/` |
| **CA3** caso negativo | ✅ (estruturado) `failed` no passo 7 ("Validar catálogo"), com a mensagem observada no `reason`: *"Sorry this user has been locked out."*. Passos 8–9 `skipped` | `runs/44c6fb27345e/` |
| **CA4** stop | ✅ `cancelled`; sessão Appium apagada pelo QAgent (`appium_session_deleted` no log); `list` → "No active sessions found."; nº de processos `node` igual antes e depois; 2.º stop → 409 | `runs/9d3384e2b111/` e repetição após ajuste |
| **CA9** segurança | ✅ password (`{{secret:demo_pass}}`) e API key ausentes de todos os `result.json`/`qagent.log`/`request.json`; todas as rotas exceto `/health` exigem `X-API-Key` (sem chave → 401; servidor sem chaves → 503); appium-mcp e API só em `127.0.0.1` | `grep` em `runs/`; `tests/test_api.py` |

**Descoberta sobre a app de exemplo (afeta o CA3):** a My Demo App Android 2.3.0 **não valida a password** do `bod@example.com`. Com `errada123`, o login foi aceite (`runs/10c05396bffc/`, screenshots dos passos 5 e 7). O caso negativo passa a usar o utilizador que a app lista como bloqueado, `alice@example.com (locked out)`. ⚠️ Atualizar a redação do CA3 no CPS ("password inválida" → "utilizador bloqueado" nesta app).

## 2. O que foi construído

| Ficheiro | Papel |
|---|---|
| `src/qagent/models.py` | Contrato Pydantic: entrada (CPS 7.4 + `steps` estruturados) e saída (CPS 7.5, superconjunto do `ResultOutput`), em camelCase |
| `src/qagent/executor.py` | `StepExecutor` (protocolo) + `StructuredExecutor`: `tap`, `type`, `scroll_to`, `assert_visible`, `assert_text`, `back`, `wait`. Espera ativa até `timeoutSec` (o UiAutomator2 não tem *implicit wait*). `{{testData.x}}` nos textos. `sessionId` explícito em todas as chamadas |
| `src/qagent/orchestrator.py` | Execução: *lock* do dispositivo → ligação MCP → sessão Appium → passos (timeout por passo, `stopOnFailure`) → evidências → limpeza garantida (também em stop/erro). Deteção de diálogo de sistema/ANR por passo. Resolução de segredos `{{secret:nome}}` → `QAGENT_SECRET_<NOME>` |
| `src/qagent/registry.py` | Registo em memória + `runs/<id>/result.json` (gravado a cada passo; recarregado no arranque; execuções interrompidas → `error`). Artefactos só por nome da lista (sem *path traversal*) |
| `src/qagent/health.py` | `/health` com cache de 30 s; dispositivos via `adb devices -l` |
| `src/qagent/runlog.py` | `qagent.log` em JSON lines, segredos mascarados (`***`) |
| `src/qagent/api.py` | FastAPI: rotas do CPS 7.9, `?wait=true`, validação → 400, CORS só para o frontend local |
| `tests/test_api.py` | 8 testes sem dispositivo (auth, 400/501/503, segredos, artefactos, stop 409, máscara) |

### Endpoints

| Método | Endpoint | Notas |
|---|---|---|
| GET | `/health` | Sem auth; 200 `ok` / 503 `degraded` |
| GET | `/mobile/devices` | Android via adb; iOS remoto se `QAGENT_IOS_REMOTE_SERVER_URL` |
| POST | `/mobile/testExecution` | 202 `{executionId, status}` + `X-Execution-Id`. `?wait=true[&waitTimeoutSec=N]` → 200 com o relatório. 501 sem `steps`, ou para iOS |
| GET | `/mobile/testExecution` | Lista (memória + disco) |
| GET | `/mobile/testExecution/{id}` | Estado, `progress` ("A executar o passo N de M") e relatório |
| POST | `/mobile/testExecution/{id}/stop` | `{id, status: "stopping"}`; 409 se já terminou |
| GET | `/mobile/testExecution/{id}/artifacts/{name}` | `result.json`, `qagent.log`, `request.json`, `step-NN.png`, `step-NN.xml` |

### Como executar

```powershell
# 1. appium-mcp (janela própria)
powershell -ExecutionPolicy Bypass -File scripts\start-appium-mcp.ps1
# 2. API — usar "python -m": os .exe do venv (uvicorn.exe, pytest.exe) são bloqueados no Windows ("Acesso negado")
$env:QAGENT_API_KEYS = "dev-key"; $env:QAGENT_SECRET_DEMO_PASS = "10203040"
.venv\Scripts\python -m uvicorn qagent.api:app --host 127.0.0.1 --port 8100
# 3. Testes
.venv\Scripts\python -m pytest -q
```

Pedidos completos em `examples/login-positivo.json` e `examples/login-negativo-bloqueado.json`:

```powershell
curl.exe -X POST "http://127.0.0.1:8100/mobile/testExecution?wait=true" -H "X-API-Key: dev-key" -H "Content-Type: application/json" --data "@examples/login-positivo.json"
```

## 3. Números (modo estruturado, sem LLM)

| Execução | Estado | Duração | Chamadas MCP |
|---|---|---|---|
| Login positivo (9 passos) | passed | 33,2 s | 38 |
| Negativo, utilizador bloqueado | failed (passo 7) | 32,1–38,6 s (inclui 10 s de espera do passo 7) | — |
| Stop no passo 4 | cancelled | 31,4 s | — |

Por passo: 0,7–2,4 s, incluindo ≈ 0,6 s de page source para deteção de diálogos e ≈ 0,25 s de screenshot. A criação da sessão (≈ 10 s) vai para o 1.º passo da contagem total. 0 ANRs.

## 4. Decisões e descobertas

1. **Dependências:** o pydantic **não** pode ser alinhado com o 2.10.6 do genai_fastapi, porque o `mcp` ≥ 1.13 exige pydantic ≥ 2.11 (com 2.10, o resolver desce o `mcp` para 1.12.4, sem `streamable_http_client`). Fica pydantic 2.14 + FastAPI 0.115.14 (avisos inofensivos `UnsupportedFieldAttributeWarning`, filtrados no pytest). Junta-se à restrição do `langchain-mcp-adapters` (F1-registo 3) → a integração no genai_fastapi (F7) vai exigir atualizar as dependências de um dos lados.
2. **Evidência do page source em cada passo:** custa ≈ 0,6 s mas permite (a) detetar ANR/diálogos de sistema, que o appium-mcp não sinaliza (F0), e (b) pôr no `reason` os textos visíveis quando um passo falha. Foi assim que a mensagem de erro do CA3 chegou ao relatório.
3. **Estados:** stop → passo em curso e pendentes ficam `skipped` ("Não executado (stop)"), não `error`. `error` fica reservado a infraestrutura (timeout do passo, erro do appium-mcp, diálogo de sistema).
4. **Concorrência:** `asyncio.Lock` único por servidor appium-mcp. Execuções simultâneas ficam `queued` ("À espera do dispositivo") até a anterior acabar (F1-registo 5.1).
5. **Segredos:** `{{secret:nome}}` resolvido do ambiente no `POST` (400 se faltar, antes de criar a execução). Os valores de chaves sensíveis (`pass|secret|token|pwd|pin`) e os segredos são mascarados no log, no `request.json` e no `reason`.

## 5. Pendentes

- **CA2/CA3 em linguagem natural** → F2/F3 (precisa de LLM com API).
- `appium_get_page_source` devolve ≈ 33 KB por passo. Para a F2 é preciso um resumo (não enviar ao LLM).
- Frontend **F4b**: o contrato está pronto (CORS para `localhost:5173`/`3000`, `X-Execution-Id` exposto, `progress` para *polling*).
