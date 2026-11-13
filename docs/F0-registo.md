# F0 — Registo da exploração (appium-mcp + cliente MCP)

> Referência: `Prompts/CPS-QAgent.md`, secção 8 (F0). Este registo alimenta o desenho do executor de passo (F2).

## 1. Ambiente (verificado em 2026-11-11)

| Item | Valor |
|---|---|
| SO | Windows 11 Pro |
| Node.js / npm | v24.15.0 / 11.12.1 |
| JDK (`JAVA_HOME`) | OpenJDK 17.0.14 em `C:\Android\JDK` (o `java` no PATH é um JRE 8; o Appium usa o `JAVA_HOME`) |
| Android SDK | `C:\Android\Sdk`, build-tools 34.0.0 e 36.0.0 |
| Emulador | AVD `MauiEmulator`, Android 16 (API 36), google_apis, x86_64, 2 GB RAM → `emulator-5554` |
| appium-mcp | **1.99.3**, instalado localmente em `tools/appium-mcp` (não via `npx`) |
| Cliente MCP | Cliente MCP no VS Code, configurado por `.mcp.json` do projeto |
| App de exemplo | Sauce Labs My Demo App Android **2.3.0** (`apps/mda-2.3.0-27.apk`) — package `com.saucelabs.mydemoapp.android`, launch activity `.view.activities.SplashActivity` |

## 2. Observações já registadas

1. **`npx -y appium-mcp@…` é frágil para arranque automático.** A primeira instalação demora vários minutos (665 pacotes). Se for interrompida, deixa a cache do `npx` corrompida (`ENOENT … package.json`). **Decisão:** no QAgent, o appium-mcp é **pré-instalado** numa pasta com versão fixa e arrancado com `node …/dist/index.js`.
2. **Handshake MCP stdio OK:** `serverInfo = {"name":"MCP Appium","version":"1.99.3"}`. **32 ferramentas** expostas com `AI_VISION_ENABLED=false` e a documentação desligada.
3. **Custo das definições de ferramentas:** a resposta de `tools/list` tem **≈ 44 KB (≈ 11 mil tokens)**. As maiores são `appium_gesture` (≈ 5,0 KB), `appium_session_management` (≈ 3,8 KB) e `appium_perform_actions` (≈ 2,9 KB). Isto confirma a necessidade da *allowlist* de ferramentas do CPS (7.7). Lista completa em `docs/appium-mcp-1.99.3-tools.json`.
4. **Tempo de arranque ≈ 33 s** (`node dist/index.js` até à resposta ao `initialize`, com a instalação local já feita). Excede o *timeout* por omissão de 30 s do cliente MCP → `MCP_TIMEOUT=120000` na configuração do cliente. **Impacto no QAgent:** um processo stdio **por execução** custa cerca de 33 s de arranque. Reavaliar na F1 entre arrancar o appium-mcp uma vez e reutilizá-lo (*pool*/`--httpStream` em *loopback*) e arrancar um por execução (CPS 7.3).
   **Causa (perfil de CPU, 2026-11-11):** ≈ 75% do tempo é I/O de ficheiros (`readFileUtf8` ≈ 22 s, `open` ≈ 17 s, `readPackageJSON` ≈ 6 s num arranque perfilado de 59 s). São milhares de ficheiros de `node_modules` lidos no arranque, com o antivírus do Windows a verificar cada abertura. **Mitigações possíveis:** (a) exclusão do antivírus para `tools/appium-mcp` (pedido à equipa de TI); (b) processo appium-mcp de longa duração reutilizado pelo QAgent; (c) *bundle* num único ficheiro (a avaliar, arriscado por causa dos drivers). Para a F0: `MCP_TIMEOUT=120000` definido como variável de ambiente do utilizador do Windows.
   **Solução adotada na F0 (2026-11-11):**
   - A extensão VS Code ignorou `MCP_TIMEOUT` e manteve o limite de 30 s.
   - O appium-mcp passou a correr como **servidor de longa duração** com `--httpStream`, ligado **só a `127.0.0.1:8080`** (`FASTMCP_HOST=127.0.0.1`). Arranque: `scripts/start-appium-mcp.ps1`.
   - O cliente MCP liga por `http://127.0.0.1:8080/sse` (`.mcp.json` com `type: http`). O *endpoint* `/sse` aceita MCP *streamable HTTP* (POST `initialize` → 200 `text/event-stream` com `mcp-session-id`) → **ponto 3 do Anexo A do CPS respondido**.
   - O fastmcp 4.26.2 usa `localhost` por omissão quando o host não é definido.
5. Ferramentas presentes que o README não destacava: `appium_get_element_attribute`, `appium_mobile_press_key`.

## 3. Cenário de exploração (a executar no cliente MCP)

**Caso de login (positivo):** "Abre a My Demo App, vai ao menu, escolhe Log In, entra com o utilizador de teste da app e confirma que o login teve sucesso."
**Caso negativo:** o mesmo com uma password errada → confirma que aparece a mensagem de erro.

Para cada caso, registar:

| Pergunta | Caso positivo — executado em 2026-11-11, 19:36–19:41, **PASSOU** | Caso negativo |
|---|---|---|
| Sequência de ferramentas chamadas (por ordem) | `select_device` → `session_management create` → `generate_locators` (ecrã inteiro) → `find_element` + `gesture tap` (menu) → `generate_locators query` ×2 (vazio) → `get_page_source saveToFile` → **ANR** → `find_element` + `tap` "Wait" → `generate_locators` → `scroll_to_element` (falhou) → `get_page_source` → `find_element` + `tap` "Wait" → `screenshot` ×2 → `find_element` com `UiScrollable` (falhou) → `app_lifecycle terminate` + `activate` → `screenshot` → `find_element` + `tap` (menu) → `scroll_to_element` "Log In" → `find_element` + `tap` → `generate_locators` (ecrã de login) → `scroll_to_element` + `generate_locators query` ×2 (confirmar credenciais) → `find_element` ×2 → `set_value` ×2 → `find_element` + `tap` (Login) → `find_element` + `get_text` (título) → `find_element` + `tap` (menu) → `scroll_to_element` "Log Out" → `screenshot` → `session_management delete` → `list`. **≈ 45 chamadas MCP**, das quais ≈ 15 só por causa do ANR. Sem o ANR, o caminho feliz tem **≈ 20 chamadas**. | Por executar |
| `select_device` auto-selecionou o emulador? | Sim. Com um só dispositivo devolveu `emulator-5554` e `capabilitiesHint = {"appium:udid":"emulator-5554"}` | |
| Como foi criada a sessão (capabilities usadas, tempo de arranque) | `platform=android`. Capabilities: as de `config/capabilities.json` mais `appium:udid` (UiAutomator2, `appium:app` = APK local, `appPackage`/`appActivity`, `appWaitActivity=*`, `noReset=false`, `autoGrantPermissions=true`, `newCommandTimeout=300`). **≈ 51 s** até à resposta, incluindo a (re)instalação da APK e dos servidores UiAutomator2 (o logcat mostra os dois `io.appium.uiautomator2.server*` atualizados). | |
| Locators escolhidos por elemento e estratégia (accessibility id / id / uiautomator / xpath) | Menu: **accessibility id** `View menu`. Item "Log In" e "Log Out": **-android uiautomator** `new UiSelector().text("Log In")` / `text("Log Out")` (o item só tem `itemTV` partilhado, sem content-desc próprio). Username: **id** `…:id/nameET`. Password: **id** `…:id/passwordET`. Botão Login: **accessibility id** `Tap to login with given credentials`. Verificação do título: **id** `…:id/productTV`. Diálogo ANR: **-android uiautomator** `text("Wait")`. **Nunca foi usado xpath.** | |
| Foi preciso `appium_get_page_source` completo, ou bastou `generate_locators`? | Para o fluxo bastou o `generate_locators`. O `get_page_source` (com `saveToFile=true`, 7,9 KB em `runs/f0/pagesources/`) só foi usado para diagnosticar o ANR: o `generate_locators query` devolvia `[]` sem explicar porquê. O XML mostrou que o ecrã era o diálogo do sistema (`package="android"`). Notas: (a) o `generate_locators` sem `query` no catálogo devolve ≈ 13 KB (25 elementos, a maioria estrelas de rating); com `query` cai para < 1 KB. (b) O `query` só procura no ecrã visível, por isso não encontra itens fora do *viewport* (ex.: "Log In" no fundo do menu). (c) `get_page_source` com `pattern` exige `saveToFile=true`; sem isso dá erro. | |
| Formato de retorno de `appium_screenshot` (imagem inline vs. caminho de ficheiro) | **Caminho de ficheiro** (`runs/f0/screenshots/screenshot_<epoch>.png`), sem imagem inline. Para ver o ecrã, o agente tem de ler o PNG à parte (custo extra em tokens). `maxWidth=400` dá PNGs de 12–29 KB. O inline só existe com `returnRawBase64=true`, que a própria descrição desaconselha a LLMs. | |
| Erros / retries / comportamentos estranhos | 1. **ANR da app** logo após abrir o menu: `Input dispatching timed out … Waited 5002ms for FocusEvent` (logcat, 19:37:58). Coincide com o SDK TestFairy a falhar a ligação (`api.testfairy.com`) e com o emulador sob pressão de memória (74 MB livres, 677 MB de swap, AVD com 2 GB). Carregar em "Wait" **não resolveu**: o diálogo reapareceu 3 vezes em segundos. **Resolvido com `app_lifecycle terminate`/`activate`**; depois disso, zero ANRs. 2. O appium-mcp **não sinaliza o ANR**: `tap`, `find_element` e `generate_locators` respondem "sucesso" ou devolvem `[]`, e o `scroll_to_element` só diz "page source did not change". Só o XML ou o screenshot revelaram o diálogo. 3. A primeira tentativa de `scroll_to_element` falhou porque o ANR estava por cima. A seguir ao restart funcionou à primeira (1 scroll, ≈ 2,1 s). 4. Todas as respostas de ação trazem um bloco `evidence://…` (JSON com `evidenceId`, `locator`, `timing.durationMs`), útil para o relatório do QAgent. | |
| Como foi feita a verificação final (asserção explícita?) | Asserção explícita em dois pontos. (1) `get_text` em `…:id/productTV` = `"Products"`: a app voltou ao catálogo após o login. (2) Menu reaberto e `scroll_to_element text("Log Out")` encontrado, ou seja, o estado mudou de *logged out* para *logged in*. Screenshot final como evidência: `runs/f0/screenshots/screenshot_1794426054351.png`. A verificação (1) sozinha é fraca, porque o catálogo também aparece sem login. O sinal forte é o (2). O MCP não tem ferramenta de *assert*: quem decide é o agente. | |
| A sessão foi apagada no fim (`action=list` vazio)? | Sim. `delete` → "Active session deleted successfully"; `list` → "No active sessions found." | |
| Duração total aproximada | **≈ 4 min** (19:36:51 → 19:40:57), dos quais ≈ 51 s na criação da sessão e ≈ 1,5 min perdidos com o ANR. Sem ANR, estimam-se ≈ 2–2,5 min, dominados pelo raciocínio do agente entre chamadas (cada ação Appium demora 45–350 ms; os `scroll_to_element` ≈ 2 s). | |

**Credenciais usadas:** `bod@example.com` / `10203040`. Foram lidas do próprio ecrã de login (`username1TV` / `password1TV`), não assumidas. Utilizadores alternativos listados pela app: `alice@example.com (locked out)` (útil para outro caso negativo) e `visual@example.com`.

## 4. Conclusões para a F1/F2

### 4.1 Decisão da F0 (2026-11-11): **CONTINUAR, com ajustes**

O appium-mcp 1.99.3 funciona em Windows com o emulador Android local. O caso de login foi executado de ponta a ponta por um agente LLM só com ferramentas MCP, sem xpath, com asserção explícita e limpeza da sessão. O caso negativo não foi executado (dispensado).

### 4.2 Pontos do Anexo A do CPS respondidos

| # | Ponto | Resposta |
|---|---|---|
| 3 | Endpoint do `--httpStream` | `/sse`, que aceita MCP *streamable HTTP* (secção 2, ponto 4) |
| 4 | Schemas das ferramentas | Capturados em `docs/appium-mcp-1.99.3-tools.json` |
| 5 | Retorno de `appium_screenshot` | **Caminho de ficheiro** (PNG em `SCREENSHOTS_DIR`); inline só com `returnRawBase64=true` |
| 7 | Auto-seleção de `select_device` | **Sim**, com um único dispositivo |
| 10 | Capabilities da app de exemplo | `config/capabilities.json`, validado (Android 16 / API 36) |
| 17 | Acesso npm/GitHub | OK (instalação local em `tools/appium-mcp`) |

### 4.3 Ajustes para a F1

1. **Transporte:** usar o appium-mcp como **servidor de longa duração** (`--httpStream`, `127.0.0.1:8080`, `scripts/start-appium-mcp.ps1`) em vez de um processo stdio por execução, porque o arranque leva ≈ 33 s. O isolamento entre execuções passa a depender de: uma sessão MCP por execução, `delete` garantido no fim e *lock* por UDID (CPS 7.3, regra 5). O stdio fica como opção quando houver exclusão do antivírus.
2. **Criação da sessão ≈ 51 s** com `noReset=false` (reinstala a APK). Para os 10 ciclos da F1, medir também com `noReset=true` e a app já instalada.
3. **Pós-condição do ciclo:** depois de criar a sessão e antes do `delete`, verificar que o ecrã em primeiro plano é da app (`package` ≠ `android`). Isto apanha diálogos ANR/sistema.

### 4.4 Requisitos para o executor de passo (F2)

1. **Deteção de diálogos de sistema.** O appium-mcp não sinaliza ANR: as ações respondem "sucesso" e o `generate_locators` devolve `[]`. Após cada passo, o executor deve verificar o `package` do ecrã. Se for o diálogo "isn't responding": 1 tentativa "Wait" e, se voltar, reiniciar a app (`app_lifecycle terminate`/`activate`) e repetir o passo. Registar o caso no relatório.
2. **Resumo de ecrã:** usar `generate_locators` **com `query`** (< 1 KB) em vez de sem filtro (≈ 13 KB) ou do `page_source`. Atenção: só vê o ecrã visível. Para elementos fora do ecrã, usar `scroll_to_element`.
3. **Allowlist mínima** (cobriu 100% do caso): `select_device`, `appium_session_management`, `appium_find_element`, `appium_gesture`, `appium_set_value`, `appium_get_text`, `generate_locators`, `appium_screenshot`, `appium_app_lifecycle`, `appium_get_page_source` (diagnóstico). As 22 restantes ficam fora → corta grande parte dos ≈ 11 mil tokens de definições.
4. **Locators:** a ordem accessibility id > id > uiautomator funcionou. Itens de lista sem id próprio (menu) precisam de `UiSelector().text(...)`.
5. **Asserções:** o MCP não tem *assert*. O executor deve pedir ao LLM uma verificação estruturada (Pydantic) baseada em `get_text` ou na presença de um elemento, e preferir sinais de **mudança de estado** (ex.: "Log Out" no menu) a sinais que também existem sem a ação (ex.: título "Products").
6. **Evidências:** cada resposta de ação traz um bloco `evidence://` com `locator` e `timing.durationMs`. Reaproveitar no relatório por passo (CPS 7.5).
7. **Orçamento:** caminho feliz ≈ 20 chamadas MCP. Cada ação Appium leva 45–350 ms e `scroll_to_element` ≈ 2 s. A latência total vai ser dominada pelo LLM.
