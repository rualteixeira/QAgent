# QAgent

O QAgent executa sozinho testes em apps móveis nativas (Android; iOS ainda por fazer). O caso de teste pode ser escrito em texto livre, em Gherkin ou como passos estruturados. Um LLM decide cada ação no dispositivo através do [appium-mcp](https://github.com/appium/appium-mcp).

O QAgent não conhece a app de antemão: recebe só o package/APK (ou nenhum, se o teste disser que apps abrir) e o caso de teste.

Cada execução produz:
- um relatório por passo: estado, motivo, força da evidência, localizadores e evidência (screenshot/XML);
- um script **Python + Appium**, gerado sem LLM, que repete o caminho fora do QAgent (QA/CI).
## Arquitetura
[arquitetura](https://github.com/rualteixeira/QAgent/blob/main/docs/ARQUITETURA.md)
## Componentes e portas

| Componente | Porta | Arranque |
|---|---|---|
| Emulador/dispositivo Android | — | AVD ou dispositivo com depuração USB (`adb devices`) |
| appium-mcp 1.99.3 (servidor HTTP, inclui Appium 3 + UiAutomator2) | 127.0.0.1:8080 | `powershell -ExecutionPolicy Bypass -File scripts\start-appium-mcp.ps1` (30–60 s) |
| API do QAgent (FastAPI) | 127.0.0.1:8100 | ver abaixo |
| Interface web (React + Vite) | 127.0.0.1:5173 | `cd frontend && npm install && npx vite` |
| Servidor Appium para os scripts gerados (opcional) | 127.0.0.1:4723 | `scripts\start-appium-server.ps1` |

- A porta 8000 está ocupada por outro serviço (GenAI-TestCases-API); não a use.
- Não corra o servidor Appium 4723 ao mesmo tempo que uma execução do QAgent no mesmo dispositivo.
- O appium-mcp não tem autenticação: mantenha-o em 127.0.0.1.

## Instalação

Requisitos: Python 3.11, [uv](https://docs.astral.sh/uv/), Node 20+, Android SDK (adb) e JDK. Os caminhos por omissão são `C:\Android\Sdk` e `C:\Android\JDK`; altere-os nos scripts `.ps1` se forem outros.

```powershell
uv sync                                         # dependências Python (.venv)
cd tools\appium-mcp; npm install; cd ..\..      # appium-mcp local (nada global)
cd frontend; npm install; cd ..
```

## Arrancar a API

```bash
QAGENT_API_KEYS=<chave-da-api> .venv/Scripts/python -m uvicorn qagent.api:app --host 127.0.0.1 --port 8100
```

Use `python -m uvicorn`: os `.exe` da venv podem estar bloqueados pela política da máquina.

### Configuração (variáveis `QAGENT_*` ou ficheiro `.env`)

| Variável | Omissão | Para quê |
|---|---|---|
| `QAGENT_API_KEYS` | (vazio → rotas protegidas respondem 503) | Chaves aceites no cabeçalho `X-API-Key`, separadas por vírgulas |
| `QAGENT_MCP_HTTP_URL` | `http://127.0.0.1:8080/sse` | Endereço do appium-mcp |
| `QAGENT_RUNS_DIR` | `runs/` | Onde ficam as execuções |
| `QAGENT_RUNS_RETENTION_DAYS` | `0` (nunca apagar) | No arranque, apaga as execuções terminadas há mais de N dias. As pastas das fases (`f0`, `f5`, …) nunca são apagadas |
| `QAGENT_CORS_ORIGINS` | localhost:5173/3000 | Origens da interface web |
| `QAGENT_SECRET_<NOME>` | — | Valor de `{{secret:<nome>}}` em `testData` (nunca vai para os logs) |

As capabilities base estão em `config/capabilities.json`. São genéricas: não indicam nenhuma app e usam `noReset: true`. O appium-mcp usa o mesmo ficheiro.

### LLM

O LLM é escolhido **por pedido**, com cabeçalhos; o QAgent não guarda chaves:

| Cabeçalho | Azure OpenAI | Gemini |
|---|---|---|
| `X-Provider` | `azure` | `gemini` |
| `X-LLM-Model` | nome do deployment | modelo |
| `X-LLM-API-Key` | chave | chave |
| `X-LLM-Endpoint` | endpoint do recurso | — |
| `X-LLM-APIVersion` | versão da API | — |

Na interface web, estes valores são introduzidos pelo utilizador. O botão **Save** guarda-os no browser, exceto a chave.

## Usar a API

```bash
curl -X POST "http://127.0.0.1:8100/mobile/testExecution" \
  -H "X-API-Key: <chave-da-api>" -H "Content-Type: application/json" \
  -H "X-Provider: azure" -H "X-LLM-Model: <deployment>" -H "X-LLM-API-Key: <chave>" \
  -H "X-LLM-Endpoint: <endpoint>" -H "X-LLM-APIVersion: <versão>" \
  -d '{
        "testExecution": "Abre a app, cria um registo com o nome {{testData.nome}} e valida que aparece na lista.",
        "app": {"android": {"appPackage": "<package.da.app>"}},
        "testData": {"nome": "Teste 1"},
        "options": {"resetApps": ["<package.da.app>"]}
      }'
```

| Rota | Para quê |
|---|---|
| `POST /mobile/testExecution` | Cria uma execução (202 + `executionId`) |
| `GET /mobile/testExecution/{id}` | Estado e relatório |
| `POST /mobile/testExecution/{id}/resume` | Continua após uma ação manual do QA (estado `waiting_for_user`, ex.: autenticação) |
| `POST /mobile/testExecution/{id}/stop` | Cancela (a sessão Appium é sempre apagada) |
| `GET /mobile/testExecution/{id}/script` | Script Python + Appium gerado a partir da execução |
| `GET /mobile/testExecution/{id}/artifacts/{nome}` | Screenshots, XML, log |
| `GET /mobile/devices`, `GET /health` | Dispositivos ligados; estado do appium-mcp, adb e node |

### Entrada

O caso de teste vem num de três campos:
- `testExecution`: texto livre, dividido em passos pelo LLM;
- `scenario`: Gherkin;
- `steps`: passos estruturados, sem LLM, ou com passos `ai`/`manual`.

Sem `app`, o teste começa no ecrã inicial e o próprio texto diz que apps abrir. Por exemplo: "vai à app X e faz…, depois vai à app Y…".

### Opções principais (`options`)

| Opção | Omissão | Notas |
|---|---|---|
| `resetApps` | `[]` | Apps cujos dados são apagados no início. **Única forma de ter um estado limpo:** o QAgent nunca apaga dados por iniciativa própria. Se incluir a app do pedido, ela volta a abrir |
| `stopOnFailure` | `true` | |
| `screenshots` | `every_step` | `every_step`, `on_failure` ou `none` |
| `maxActionsPerStep` | 8 | Orçamento de ações do LLM por passo |
| `timeoutPerStepSec` | 90 | Passos com LLM: mínimo de 180 s |
| `humanTimeoutSec` | 600 | Espera máxima por uma ação do QA |
| `infraRetries` | 1 | Novas tentativas de ligação/criação da sessão. **Nunca** repete passos |
| `reportLanguage` | pt-PT | Idioma dos motivos escritos pelo LLM |
| `promptVersion` | `e2` | Versão da prompt do executor (`e1` para reproduzir execuções antigas) |

### Leitura do resultado

- `status`: `passed`, `failed` (a app não fez o esperado), `error` (não se conseguiu concluir) ou `cancelled`.
- `failureCategory`: `app`, `environment`, `llm` ou `appium_mcp`.
- `steps[].outcome`, a força da evidência:
  - `verified`: verificado pela máquina num ecrã relido;
  - `executed`: ação feita, resultado não verificado nesse passo;
  - `inconclusive`: só o juízo do LLM, ou erro.
- `device`, `appVersions`, `promptVersions`: o ambiente da execução.

## Scripts gerados

```powershell
pip install Appium-Python-Client
powershell -ExecutionPolicy Bypass -File scripts\start-appium-server.ps1   # noutra janela
python teste_gerado.py
```

O cabeçalho do script indica:
- as variáveis de ambiente necessárias (segredos);
- os localizadores frágeis;
- o dispositivo e as versões em que o caminho foi gravado.

## Desenvolvimento

```bash
.venv/Scripts/python -m pytest -q                                  # testes (sem dispositivo nem LLM)
.venv/Scripts/python scripts/run_case.py examples/<caso>.json      # caso real contra a API (LLM das variáveis QAGENT_DEV_*)
.venv/Scripts/python scripts/f5_batch.py ...                       # N execuções + métricas
```

- `tests/test_prompts_app_agnostic.py` falha se uma prompt mencionar termos das apps de teste. As prompts têm de servir qualquer app.
- `examples/` tem casos da My Demo App (regressão); `examples/blind/` tem casos para apps de sistema nunca usadas na afinação.
- Os registos de cada fase estão em `docs/` (F0–F5, G).

## Limitações conhecidas

- **iOS:** não implementado. Precisa de um Mac.
- **Uma execução de cada vez por dispositivo:** dispositivos diferentes podem correr em paralelo.
- **Interrupções no script gerado:** o script trata diálogos de permissões e mudanças de app, mas uma notificação por cima de um botão pode fazer falhar um toque.
- **Resultados esperados ambíguos:** por exemplo, "a app indica que terminou" é julgado pelo LLM e pode variar entre execuções. Prefira resultados observáveis: um texto, um número de itens, um estado de um elemento.
