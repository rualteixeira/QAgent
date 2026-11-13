# Fase G — Generalização: agente agnóstico à app (2026-11-12)

> Fase acrescentada entre a F3 e a F5. Motivo: o executor tinha sido afinado só com a Sauce Labs My Demo App, mas o QAgent tem de testar qualquer app (finanças, banca, e-commerce, temporizadores…) **sem saber de antemão que app é**. Só recebe a app (package/APK) e o caso de teste.

## 1. Regras

1. Nenhum conhecimento de apps concretas no código, *prompts* ou heurísticas: só a estrutura Android (classes, texto, content-desc, resource-id, *flags*, posição).
2. Avaliação **às cegas**: apps nunca usadas para afinar, só com o caso em linguagem natural e o package.
3. Toda a correção tem de ser genérica; a My Demo App passa a ser só regressão.

## 2. O que mudou

| Antes (F2/F3) | Agora |
|---|---|
| Resumo do ecrã via `generate_locators` (sem posições; elementos sem rótulo descartados, o que escondia botões só-ícone) | **Modelo do ecrã próprio** (`src/qagent/screen.py`) a partir do XML: todos os elementos interativos, incluindo os só-ícone ("(no label)" + nome do resource-id), estado (checked/selected/disabled/password/focused), região no ecrã, aviso de diálogo de sistema. Textos dentro de itens clicáveis passam a ser o rótulo do item. ~700 tokens com um menu aberto |
| O LLM escrevia `strategy`/`selector` (podia inventar locators) | O LLM escolhe **refs** (`e7`); o QAgent converte-as no locator mais estável: accessibility id > id > texto > resourceId+instance (frágil) > **coordenadas** (frágil). Textos com dígitos (dinâmicos) e textos de campos editáveis são marcados frágeis |
| 8 ferramentas (tap, type, read, check, scroll_to, back, get_screen, finish) | 13: `tap`, `long_press`, `type_text` (+Enter), `read_text` (texto + estado), `swipe`, `scroll`, `scroll_to_text`, `press_key` (back/enter/delete/tab/search/escape/space/hide_keyboard), `wait`, `wait_for_text` (aparecer/desaparecer), **`look_at_screen`** (screenshot para o modelo multimodal), `get_screen`, `finish_step` |
| *Prompt* com exemplo da app ("Log In") | *Prompt* neutro: descobrir a app pelo ecrã, elementos só-ícone, overlays, scroll antes de desistir, esperas para comportamento temporal, diálogos de sistema |
| Pedir só `appPackage` herdava a activity e o APK da app por omissão | O QAgent envia `""` nessas capabilities (o appium-mcp junta o seu `CAPABILITIES_CONFIG` ao pedido e remove os valores vazios); o UiAutomator2 resolve a activity de arranque |
| Repetição de chamadas falhadas bloqueada por assinatura de locator | Qualquer chamada idêntica feita pela 3.ª vez é rejeitada (exceto wait/scroll/swipe) |

## 3. Resultados

**Regressão (My Demo App, mesmos pedidos):** CA2 `passed` 6/6 (`runs/95fe7379c0db`); CA3 `failed` no Then com *"Sorry this user has been locked out."* (`runs/6129c6498998`).

**Às cegas (apps nunca usadas para afinar; Azure OpenAI GPT-5.1):**

| App (package) | Caso (só linguagem natural) | Resultado | Verificação independente |
|---|---|---|---|
| Relógio (`com.google.android.deskclock`) | "Cria um temporizador de 5 s e inicia-o. Valida que, quando o tempo acaba, a app indica que terminou." | ✅ 3/3, 60 s, 14 chamadas, 29,8 k tokens (`runs/8b5e87c49633`) | Screenshots: "5s Timer" a contar → cartão expirado (−28 s) |
| Contactos (`com.google.android.contacts`) | "Cria um contacto com nome e telefone (testData), guarda-o e valida nome e número." | ✅ 5/5, 49 s, 14 chamadas, 24,7 k tokens (`runs/d7ff38652cdc`) | Screenshot: "Teste QAgent", (912) 345-678 |
| Definições (`com.android.settings`), Gherkin | "Given definições de ecrã / When ativo o tema escuro / Then fica ativo" | ✅ 3/3, 38 s, 9 chamadas, 15,8 k tokens (`runs/daeb11cd763b`) | `settings get secure ui_night_mode`: 1 → **2** (escuro). Reposto para claro depois |

O agente descobriu sozinho o separador Timer e o teclado numérico, o botão "Create contact" e os campos do formulário, e o caminho "Display & touch → Dark theme".

## 4. Limitações conhecidas (por testar)

- **Banca/fintech:** `FLAG_SECURE` (screenshots pretos e possivelmente sem árvore), deteção de emulador/root, OTP por SMS, biometria. Requerem decisões de ambiente (dispositivo real, contas de teste, *bypass* de OTP).
- **WebViews/híbridas:** não há troca de contexto (`appium_context`); só é visível o que o UiAutomator2 expõe.
- **Flutter sem semantics / canvas / jogos:** depende de `look_at_screen` + coordenadas; não avaliado.
- **Custo:** o modelo do ecrã completo aumentou os tokens do CA2 (21 k → 32 k). A otimizar na F5 (ex.: omitir o conteúdo por trás de overlays, resumir listas longas).
- **Normalizador:** às vezes divide uma frase em passos redundantes ("cria **e** inicia" → dois passos).
- `scripts/f2_step.py --provider fake` usa o guião antigo (ferramentas por locator) e deixou de servir; o executor real continua coberto pelos testes via API.
- Os testes alteram o estado do dispositivo (ex.: contacto "Teste QAgent" criado). Para execuções repetidas é preciso uma política de limpeza/estado inicial por app.

## 5. Testes com várias apps, identificadas pelo nome (2026-11-12)

**Requisito:** "vai à app X e faz isto; depois de validares, vai à app Y e faz aquilo". A app vem no texto do teste, não no pedido.

### O que foi construído
- **Pedido sem app** → a sessão começa no **ecrã inicial do dispositivo** (`appPackage/appActivity/app = ""`, `noReset`, `autoLaunch=false`). Já não existe app por omissão; os exemplos da My Demo App indicam-na explicitamente.
- **`list_apps`**: apps com ícone no launcher (consulta MAIN/LAUNCHER via adb: 24 no emulador, contra 258 packages no appium-mcp; *fallback* para a lista do appium-mcp com filtro, para dispositivos remotos). O Android não expõe o nome visível: o modelo associa pelo package e, se não for claro, procura a app pelo nome no launcher (`press_key home`).
- **`open_app(package, restart)`**: abre ou troca de app na mesma sessão (`appium_app_lifecycle activate`); recusa packages não instalados.
- **Normalizador:** mantém os passos "vai à app X" no idioma do teste (antes misturava inglês com português e o modelo chegou a responder em espanhol).
- **`options.resetApps`**: apps cujos dados são apagados no início (estado limpo e repetível). Explícito, packages validados. Campo no ecrã.
- **Histórico de passos:** o executor recebe o que os passos anteriores fizeram.
- **`finish_step.how`** (passos `[WHEN]`): `performed` (exige uma ação bem-sucedida) | `already_done_by_step` (validado contra o histórico; evita repetir ações irreversíveis, ex.: pagamentos) | `already_true_before_test` → o passo fica **`error`**: "Estado pré-existente… use options.resetApps".
- **Aviso de interrupção:** se outra app passar para primeiro plano sem ter sido pedida, o resultado da ação avisa que pode não ter tido efeito.
- **Diálogos de erro:** a deteção de bloqueio usa os resource-ids `android:id/aerr_*` (independentes do idioma). Notificações, dicas e permissões passam a ser "sobreposições", não erros. Validado com o XML real da F0 (deteta) e com a dica "Viewing full screen" (não deteta).

### Caso às cegas: Relógio + Contactos (`examples/blind/multi-app-relogio-contactos.json`, sem app no pedido)
"Vai à app do relógio, cria um temporizador de 10 s e inicia-o. Depois vai à app de contactos e cria um contacto {{testData.name}}; valida que foi guardado. A seguir volta à app do relógio e valida que o temporizador já terminou."

| Execução | Resultado | O que mostrou |
|---|---|---|
| `4c57157b78b5` | error | O alarme do temporizador em ecrã inteiro foi tomado por ANR → **corrigido** (deteção por `aerr_*`) |
| `fce1335933c8` | failed | Temporizador antigo de uma execução anterior ainda a tocar; "cria temporizador" passou sem ação → **corrigido** (`resetApps` + regra `[WHEN]`) |
| `0e9fbfa7d0d4` | failed | Passos 1–7 corretos; Then final mal interpretado (−44 s lido como "não terminou"); passo "inicia" repetiu pausa/início por causa da regra `[WHEN]` → **corrigido** (histórico + `already_done_by_step`) |
| `8b1b624b86b8` | passed* | *Falso positivo no passo 5 ("o contacto já existe", de uma execução anterior) → **corrigido** (`how=already_true_before_test` → error) |
| `12e279361186` | failed | O alarme interrompeu o "Save"; o Then detetou corretamente que o contacto não foi guardado → **corrigido** (aviso de interrupção) |
| `cb83917df9cc` | **passed 8/8** | Genuíno: o alarme interrompeu o "Save", o aviso disparou, o agente voltou aos Contactos e guardou. 100 s, 28 chamadas, 76,5 k tokens |
| `265f1f1a16e4` | error (honesto) | Contactos abriram no "Multi App" da execução anterior → **"Estado pré-existente"** em vez de falso positivo |

### Limites e notas
- O caso tem uma corrida de tempo embutida (um temporizador de 10 s a tocar durante a criação do contacto): é um bom teste de interrupções, mas é intrinsecamente instável.
- Para ser repetível, os contactos têm de ser limpos (`resetApps` com `com.android.providers.contacts` apaga **todos** os contactos do dispositivo). Decisão em aberto; não aplicado.
- A interpretação de resultados ambíguos ("o temporizador terminou" com contagem negativa) não é consistente entre execuções. Casos de teste com o resultado esperado explícito reduzem a ambiguidade.
- Custo: 40–77 k tokens por execução de 8 passos com 2 apps; a otimizar na F5.

## 6. Autenticação pelo QA — humano no circuito (2026-11-12)

**Requisito:** se a app pedir autenticação, é o QA que introduz as credenciais no dispositivo; o teste só continua depois disso (evita confundir o agente e mantém as credenciais fora do QAgent/LLM).

### Comportamento
- **Pausa automática:** se aparecer um ecrã de autenticação (login, PIN, OTP, biometria…) e o passo **não** fornecer credenciais por placeholders de testData, o agente **não tenta autenticar**: chama `request_human("…")`.
- **Pausa explícita:** passo "o QA/tester faz … manualmente" (o normalizador mantém-no como passo próprio) ou ação estruturada `{"action": "manual", "text": "…"}` (não precisa de LLM).
- **Execução em pausa:** estado `waiting_for_user`, `progress.awaitingUser` (instrução) e `awaitingSince`. O ecrã mostra um aviso com o botão **Continue** → `POST /mobile/testExecution/{id}/resume` (409 se não estiver à espera). O **Stop** funciona durante a pausa.
- **Tempos:** a espera não conta para `timeoutPerStepSec`; tem limite próprio `options.humanTimeoutSec` (600 s por omissão; esgotado → passo `error`).
- **Depois do Continue:** o passo é repetido a partir do ecrã atual, com a nota do que o QA fez. O agente declara `how=done_by_tester`, que só é aceite se houve de facto uma intervenção do QA nesse passo. Fica registado como ação `human_input` ("done by user after Ns").
- **Credenciais fornecidas no teste** (`{{testData.*}}` / `{{secret:*}}`): o agente autentica sozinho, como antes.

### Verificação (Azure OpenAI, My Demo App)
| Execução | Caso | Resultado |
|---|---|---|
| `c86fc3922fd3` | "Vai ao ecrã de Log In e faz login. Valida que o menu mostra Log Out" (sem credenciais) | Pausou no passo 2 ✅; após o login do QA o passo ficou `error` "estado pré-existente" → **corrigido** (`how=done_by_tester`) |
| `b338072e894e` | idem | ✅ **passed 3/3**: pausa → QA faz login (9 s) → Continue → "ação feita pelo tester" → Then "Log Out" visível |
| `d366f7e0876a` | CA2 (credenciais em testData) | ✅ passed 5/5, **sem pausas** (agente autentica sozinho) |

Testes unitários: `tests/test_human.py` (pausa → resume → continua; 409 fora da pausa; passo `manual` sem LLM). Total: 16.

## 7. Primeiros testes manuais (eShop + PayU, 2026-11-12)

Caso de teste, sem app no pedido: *"Abre app eShop depois valida quantos produtos tem no carrinho. Verifica no carrinho quais sao os produtos. Depois vai a app payu e verifica se tem produtos associados ao carrinho tambem"*.

| Execução | Resultado | Problema → correção (genérica) |
|---|---|---|
| `4da82ac7d2f9` (variante só eShop) | ✅ passed 4/4 | — |
| `0a1f69bfdcbe` | error no passo 5 | Na PayU, 8 scrolls seguidos à procura de um carrinho → `maxActionsPerStep` → **error**. Correções: (1) o `scroll` deteta o fim do conteúdo (ecrã igual depois do scroll → "end of content"); (2) orçamento de ações esgotado → o agente é obrigado a dar o **veredicto** com o que observou (numa verificação, "procurei e não encontrei" é `failed`, não `error`) |
| `f5244b700876` | failed no passo 2 | A sessão começou com a PayU em primeiro plano; "Abre app eShop" → o modelo abriu `com.payu.testapp` sem consultar a lista, e respondeu em espanhol. Correções: (3) aviso de coerência no `open_app` quando o package não tem relação com o nome da app do passo (mostra a lista de apps; aviso, não recusa); (4) `options.reportLanguage` (pt-PT por omissão) para motivos e instruções |
| `5c6fa7f5e51a` | ✅ **comportamento correto**: passos 1–4 passed; passo 5 **failed** com veredicto ("na PayU Demo App não existem produtos associados ao carrinho… apenas Amount, Environment, Merchant Key, Email e PAY NOW") | — |

## 8. G2 — Prompts versionadas (2026-11-13)

- `src/qagent/prompts.py`: `e1` (prompt anterior, literal, ~1151 tokens), `e2` (sem duplicações, agrupada em "Acting"/"Verdict", ~774 tokens), `n1` (normalizador). Escolha por pedido em `options.promptVersion`; o resultado regista `promptVersions`.
- `tests/test_prompts_app_agnostic.py` verifica todas as versões (sem termos das apps de teste).
- A/B no emulador, CA2 em texto livre, 3 execuções de cada:

| Versão | Passou | Duração média | Tokens de entrada (média) | Tokens de saída | Localizadores estáveis |
|---|---|---|---|---|---|
| e1 | 3/3 | 37,2 s | 25 286 | 377 | 100% |
| e2 | 3/3 | 39,7 s | 23 999 (−5%) | 449 | 100% |

- CA3 (Gherkin, utilizador bloqueado) com e2: o WHEN passou e o THEN falhou corretamente (categoria `app`).
- Decisão: `DEFAULT_EXECUTOR = "e2"`; e1 mantém-se para reproduzir execuções antigas.
- Nota: a prompt fixa é só uma pequena parte dos tokens; o grosso vem das descrições do ecrã. Uma redução maior teria de vir daí.

## 9. G3 — Controlo da execução (2026-11-13)

Tudo aditivo: os campos e o comportamento anteriores mantêm-se.

- **Força da evidência por passo** (`steps[].outcome`, `outcomes` no resultado):
  - `verified`: confirmado por uma verificação da máquina num ecrã relido (asserção, `wait_for_text`, passos `assert_*`).
  - `executed`: a ação foi feita, mas o resultado não foi verificado nesse passo.
  - `inconclusive`: só o juízo do LLM, ou o passo terminou em erro.
- **Falha de um THEN também é verificada:**
  - a asserção esperada é relida no ecrã e tem de NÃO se verificar (`not_met`);
  - se afinal se verifica, o veredicto é contestado uma vez;
  - se o modelo falhar sem asserção, é-lhe pedida uma vez.
  - Antes, o CA3 ficava `inconclusive`; agora fica `verified` (2/2 no emulador).
- **Novas tentativas só para infraestrutura** (`options.infraRetries`, omissão 1, máx. 3):
  - repete só a ligação ao appium-mcp e a criação da sessão;
  - nunca repete um passo: as ações não são idempotentes e uma falha da app não se repete até passar;
  - a verificação do dispositivo (G1) continua a falhar logo, sem novas tentativas;
  - o número de tentativas fica em `metrics.infraRetries`.
- **Bloqueio por dispositivo:**
  - substitui o bloqueio único;
  - sem `device.udid` no pedido, usa o 1.º dispositivo pronto, que passa a ser enviado também ao `select_device`.
- **Versões:**
  - `device.platformVersion` e `device.model` (getprop);
  - `appVersions` (versionName via `dumpsys package`) da app do pedido, das apps em `resetApps` e das apps abertas durante o teste;
  - o script gerado indica-as no cabeçalho;
  - a interface mostra a evidência por passo, o dispositivo, as versões e as novas tentativas.
- **Testes:** 54 automáticos. Emulador: CA2 passou (1 verified, 2 executed); CA3 falhou como esperado (categoria `app`, THEN `verified`).

## 10. G6 — Higiene da configuração (2026-11-13)

- **`config/capabilities.json` genérico:** sem app (APK, package e activity da My Demo App removidos) e sem nome de AVD; passou a ter `noReset: true`.
  - Consequência: o QAgent **nunca apaga dados de uma app por iniciativa própria**. Antes, toda a app pedida era limpa pelo Appium (`noReset: false`), incluindo, por exemplo, uma sessão iniciada à mão pelo QA. O estado limpo passa a ser pedido com `options.resetApps`.
  - Os exemplos da My Demo App e os casos `blind` do Relógio e dos Contactos passaram a declarar `resetApps`.
- **Erro encontrado e corrigido:** `resetApps` com a própria app em teste fechava-a (`pm clear`) e ninguém a reabria. O agente via o ecrã inicial e pedia ajuda ao QA (a execução ficava em `waiting_for_user`).
  - Antes, o `noReset: false` escondia o problema.
  - Agora o QAgent reabre a app do pedido depois de a limpar, e o script gerado faz o mesmo (`activate_app`, `no_reset = True`).
- **Pastas do appium-mcp:** `SCREENSHOTS_DIR` e `PAGE_SOURCES_DIR` passaram de `runs/f0/` para `runs/_mcp-server/` (sugestão do F1-registo 5.5). Só tem efeito no próximo arranque do appium-mcp.
- **Retenção:** `QAGENT_RUNS_RETENTION_DAYS` (omissão 0 = desligada). No arranque, apaga só as pastas de execução (id de 12 hex) terminadas há mais de N dias; nunca as que estão em curso nem as das fases.
- **README.md:** instalação, portas, configuração, LLM por cabeçalhos, API, opções, leitura do resultado, scripts gerados e limitações.
- **Testes:** 56 automáticos. No emulador:
  - CA3 falhou como esperado (THEN `verified`) e CA2 passou;
  - o 1.º passo do Relógio passou com `resetApps`;
  - o THEN do Relógio ("a app indica que terminou") passou 1/3 com e2 e falhou 1/1 com e1.
- **Porque falha o THEN do Relógio:** nesta versão do Relógio o fim do tempo só se vê pelo contador negativo ("−26"); não aparece nenhum texto de fim. O LLM ora aceita isso como indicação, ora não.
  - Não é regressão da prompt nem das permissões: POST_NOTIFICATIONS está concedida.
  - É um resultado esperado ambíguo; o README recomenda resultados observáveis.

## 11. G4 — Decomposição do executor LLM (2026-11-13)

O `ai_executor.py` passou de 813 para 144 linhas e ficou só com o ciclo ReAct. As partes foram para o subpacote `qagent/agent/`:

| Módulo | Responsabilidade | Linhas |
|---|---|---|
| `errors.py` | `HumanInputRequired`, `PreexistingState`, `ToolMisuse` | 19 |
| `schemas.py` | argumentos das ferramentas e do veredicto (`ALL_SCHEMAS`, verificados pelo teste de agnosticismo) | 96 |
| `device.py` | último ecrã, ref → elemento, localizar, gestos, teclas | 109 |
| `recording.py` | registo de ações/locators e máscara de segredos | 40 |
| `navigation.py` | apps instaladas, `open_app` (arranque a frio na 1.ª vez), relação package ↔ passo | 54 |
| `state.py` | estado POR PASSO (contadores, contestações, imagem pendente) | 23 |
| `tools.py` | as 16 ferramentas do LLM e `_act` (ecrã novo, mudança de app) | 289 |
| `verdict.py` | regras do veredicto (G1/G3) e asserções estruturadas | 142 |
| `transcript.py` | mensagens para o LLM e compactação dos ecrãs antigos | 56 |

- **Sem mudança de comportamento.** A interface pública mantém-se (`AiStepExecutor`, mesmo construtor, `HumanInputRequired`, `PreexistingState`).
  - O estado por execução (último ecrã, apps instaladas, apps abertas) e o estado por passo passaram a estar separados de forma explícita.
  - A deteção de mudança de app pedida (`open_app`/`press_key`) deixou de depender do nome interno da função (`__qualname__`) e passou a ser um parâmetro explícito.
- **Única diferença visível para o LLM:** o título do schema aninhado da asserção passou de `_Assertion` para `Assertion`.
- **Testes:** 56 automáticos. O teste de agnosticismo passou a ler todos os módulos de `qagent/agent/`.
- **Emulador:**
  - CA2 passou 2/2 (36–40 s, 23–26 k tokens, como antes);
  - CA3 falhou como esperado (THEN `verified`);
  - Contactos (`blind`) passou.
- **Observação:** uma 1.ª execução do CA2 deu erro (orçamento esgotado no passo do menu). Havia temporizadores do Relógio, deixados por execuções anteriores, ainda ativos; o agente acabou noutras apps.
  - Depois de limpar o Relógio, o CA2 passou 2/2.
  - É mais um caso de interferência de outra app em segundo plano (ver secção 5); não é regressão.

## 12. Scripts gerados: pesquisa de texto e toques por coordenadas (2026-11-13)

O script da execução `a5a5b5674315` (eShop + My Demo App) falhou em `wait_text('.NET BOT BLACK SWEATSHIRT')`, embora o produto estivesse no ecrã.

- **Erro 1 — `wait_text` nunca encontrava textos com `.`, `(`, `$`, `?`…**
  - O parser de `UiSelector` do Appium não interpreta barras invertidas. O regex gerado (`re.escape` + `\`) ficava com uma barra literal e falhava sempre.
  - Confirmado no emulador: `textMatches("(?i).*\.NET…")` → 0; `textMatches("(?is).*[.]NET…")` → 1; `textContains` → 1. `\"` é aceite.
  - Correção: `text_regex()` no script gerado, sem barras: os caracteres especiais passam a `[c]`; `"`, `\`, `[`, `]`, `^` e `&` passam a `.`.
- **Erro 2 — `open_app` não esperava pela app.** O passo seguinte via ainda o launcher (aviso "interrupção"). Agora espera até 15 s que a app fique à frente.
- **Erro 3 — toques por coordenadas às cegas.**
  - Neste eShop (.NET MAUI), os botões "+" e o carrinho não têm id, texto nem descrição, por isso a única forma de lhes tocar é por coordenadas.
  - O script tocava o ponto gravado fosse qual fosse o ecrã: podia tocar noutra coisa e continuar a passar.
  - Agora cada ação por coordenadas grava `target` (classe, posição e, se estável, texto/descrição do elemento). É genérico: só usa a estrutura do Android.
  - O script gerado chama `check_target()` antes de tocar e falha com "ecrã diferente da gravação" se o elemento não estiver lá (tolerância de ±12 px, espera até 5 s).
  - Scripts de execuções antigas (sem `target`) mantêm o comportamento anterior.
- **Validação:**
  - 61 testes automáticos.
  - Nova execução do mesmo caso (`73ff3288b0cb`): passou, com `target` gravado para o botão do carrinho.
  - O script passou no mesmo ecrã.
  - Com o ecrã a 400x800 (como noutro dispositivo), falhou de propósito: "ecrã diferente da gravação… encontrado ImageView". Antes, tocaria na imagem de um produto.
- **Limites que ficam:**
  - O script continua a depender da posição dos elementos sem identificador; a solução real é a app expor `AutomationId`.
  - As verificações escolhidas pelo agente podem ser mais fracas do que o caso (ex.: "quantos" verificado só pela presença de um produto). Casos com valores concretos dão verificações fortes.
- **Observação lateral:** com o eShop já aberto antes do teste, o agente declarou "abrir a app" como `already_true_before_test`, e a execução terminou em erro de ambiente. Para passos de navegação ("abrir a app X"), abrir de novo seria mais útil. Fica para avaliar.
- **Adenda — toque no launcher antes de `open_app`:** na execução `c101e35319fa`, o agente tocou num cartão dos recentes (`nexuslauncher:id/task_view_single`), sem efeito, e depois abriu a app com `open_app`. O script repetia esse toque e falhava, porque o ecrã de recentes não estava aberto.
  - Regra nova no codegen: um toque/gesto num elemento do launcher (`launcher`/`.home` no localizador), seguido de `open_app` no mesmo passo, é omitido.
  - O script gerado de novo passou no emulador. 62 testes automáticos.

## 13. "Estado pré-existente" usado à toa nos passos de ação (2026-11-13)

- **Execução `57db1a762618`:** "adiciona dois produtos ao carrinho" → o modelo abriu a app, viu o contador já com 2 e declarou `already_true_before_test`, sem agir. A execução terminou em erro de ambiente. O mesmo aconteceu em `1f2d16848337` com "abre a app eShop" quando a app já estava aberta.
- **Causa:** o modelo confunde dados que já existem com a ação já feita. Não há aprendizagem entre execuções (cada uma começa do zero), por isso o comportamento varia de execução para execução até a regra mudar.
- **Correção (código, `qagent/agent/verdict.py`):** `already_true_before_test` é contestado UMA vez. Dados existentes não provam que este teste fez a ação nem impedem de a fazer de novo, por isso o modelo é instruído a agir e terminar com `how=performed`. Se insistir, continua a ser erro de ambiente (ex.: criar um registo único que já existe). Não é contestado com o orçamento de ações esgotado.
- **Testes:** 63 automáticos (2 novos). A validação no emulador fica pendente: o servidor Appium 4723 estava ligado.
- **Universalidade garantida por teste:**
  - `test_every_message_sent_to_the_llm_is_generic` lê todas as constantes de texto de `ai_executor.py` e `qagent/agent/*.py` (exceto docstrings). Abrange as mensagens de rejeição/contestação do veredicto, os avisos das ferramentas e as mensagens do ciclo.
  - Falha se aparecer um termo das apps de teste. Verificado com uma fuga simulada ("cart items" na contestação nova) → detetada.
  - Total: 64 testes automáticos.

## 14. Normalizador n2 — não inventar valores esperados (2026-11-13)

- **Execução `aca62eb64746`:** com a correção da secção 13, o passo 1 já adicionou os dois produtos (contador 2 → 4). O passo 2 falhou porque o normalizador transformou "verifica e **indica** o número total de produtos" em "Then o carrinho contém um total de **dois** produtos". Esse valor foi deduzido de "adiciona dois produtos" e não está no caso. A app já tinha 2 itens, por isso o total era 4.
- **`NORMALIZER_N2` (= n1 + 1 regra, genérica):**
  - um valor (número, texto ou estado) só aparece num THEN se o caso o disser explicitamente;
  - "verificar/ler/contar/indicar" sem valor dá um THEN que observa e reporta.
  - `DEFAULT_NORMALIZER = "n2"`; a n1 mantém-se para reproduzir execuções antigas.
- **A/B sem dispositivo (mesmo LLM):**

| Caso | n1 | n2 |
|---|---|---|
| Caso eShop + PayU ("indica o número total") | inventou "dois" em 1/2 | 3/3 "o número total… é mostrado e indicado" |
| "valida que a lista tem 5 notas" (valor explícito) | — | 3/3 mantém "5 notas" |
| "verifica qual é a versão do Android" | — | 3/3 "a versão… é apresentada" |
| "valida que aparece um alarme às 7:00" (valor explícito) | — | 3/3 mantém "7:00" |

- **Testes:** 64 automáticos (o teste de agnosticismo cobre a n2). A validação no emulador fica pendente: o servidor Appium 4723 estava ligado.
- **Validação no emulador (secções 13 e 14), sem `resetApps`:**

| Execução | Caso | Resultado |
|---|---|---|
| `3da1e04e57df` | eShop + PayU (carrinho já com itens) | ✅ 5/5: adicionou 2 produtos; o THEN reportou o total observado (4) |
| `12809dc7f695` → `80ff5573d1b4` | Relógio (blind): "cria um alarme às 7:00", 2× seguidas | ✅ 2/2: na 2.ª criou outro alarme (não declarou estado pré-existente) |
| `14f4122da11f` → `463f9a9e6db6` | Contactos (blind): "cria o contacto Teste Duplicado", 2× seguidas | ✅ 2/2: na 2.ª criou outro contacto |

  - Nos casos blind o modelo não chegou a declarar `already_true_before_test`. A contestação não foi necessária, mas também não houve regressão.
  - Os alarmes de teste foram apagados depois (`pm clear` do Relógio), para não tocarem e interromperem testes futuros.

## 15. App errada registada depois de `open_app` (2026-11-13)

- **Script da execução `1801eaa6a4b2`:** falhou no passo 6 ("interrupção: com.payu.testapp à frente; a voltar a com.android.settings").
  - Depois de `open_app(com.payu.testapp)`, o ecrã tinha elementos de duas apps, e `app_switched` registou a 1.ª por ordem alfabética: `com.android.settings`.
  - O script gerado fazia `expect_app('com.android.settings')` e "voltava" para as Definições.
- **Correções (genéricas):**
  1. `agent/tools.py` → `foreground_package()`: a app pedida em `open_app` > uma app nova que não seja do sistema > uma app que não seja do sistema. Nunca a ordem alfabética.
  2. `codegen.py`: um `app_switched` logo a seguir a `open_app` não gera `expect_app` (o `open_app` já define a app esperada). Isto também corrige scripts de execuções gravadas antes da correção 1.
- **Validação:** 66 testes automáticos (3 novos). O script de `1801eaa6a4b2`, gerado de novo, passou no emulador (com Enter no passo manual).

## 16. Ferramenta `close_apps` (2026-11-13)

- **Execução `1801eaa6a4b2`:** "fecha todas as apps" não tinha ferramenta, por isso o agente pedia ao QA para o fazer à mão. No script isso ficava como `manual_step`, à espera de Enter.
- **Ferramenta nova `close_apps(packages?)`** (genérica):
  - com lista, termina essas apps;
  - sem lista, termina as apps usadas no teste (`open_app` + mudanças de app registadas) e a app à frente, exceto as do sistema e o launcher;
  - depois vai para o ecrã inicial;
  - termina = forçar paragem; os dados das apps ficam;
  - as apps fechadas voltam a abrir a frio.
- **Script gerado:** `close_app(pkg)` por cada app + `press_keycode(3)` + `expect_app(None)`. A mudança para o launcher registada a seguir já não define a "app esperada".
- O passo conta como ação real (outcome `executed`).
- **Testes:** 69 automáticos (3 novos). A validação no emulador fica pendente: o servidor Appium 4723 estava ligado.
- **Ecrã inicial perguntado ao Android (genérico, qualquer fabricante):**
  - `apps.home_package()` usa `cmd package resolve-activity -a MAIN -c HOME`; no emulador devolve `com.google.android.apps.nexuslauncher`.
  - Fica registado em `device.homePackage`.
  - É usado por `close_apps` (nunca fecha o ecrã inicial), pelas versões das apps e pelo codegen (toques no ecrã inicial antes de `open_app`, mudanças para o ecrã inicial).
  - A pista pelo nome ("launcher", ".home") só é usada quando o Android não responde (execuções antigas, dispositivo remoto sem adb). Quando o ecrã inicial é conhecido, a pista não é usada: um package como `com.example.homebanking` não é tratado como ecrã inicial.
  - Testes: 71 (2 novos, com um ecrã inicial `com.vendor.home` sem "launcher" no nome).

## 17. Scripts: ecrã ainda a carregar e elementos tapados (2026-11-13)

- **Script de `18af9237ab93`:** falhava de forma instável (uma vez no passo 4, duas no passo 3). Foi diagnosticado com o próprio script instrumentado (posição de cada toque + captura depois).
  1. **Ecrã ainda a carregar.** O script abria o eShop e fazia logo os scrolls com o catálogo a carregar, por isso a lista ficava noutra posição.
     - Correção: `wait_stable()` (espera que o ecrã deixe de mudar, como o agente) depois de `open_app`, toques e scrolls.
     - Correção: `find()` desliza a lista até ao elemento se ele não aparecer em 3 s (`UiScrollable.scrollIntoView`), em vez de confiar na distância dos scrolls gravados.
  2. **Elemento tapado por outro.** Com a lista noutra posição, o centro do preço "$17.000" (240,492) ficava debaixo do botão flutuante do carrinho [236,476][292,532]. O toque abria o carrinho.
     - Correção genérica `screen.free_point()`: se o centro do alvo estiver tapado por outro elemento clicável (que não é o próprio, nem o contém, nem está dentro dele), toca-se num ponto livre do alvo.
     - Usada pelo agente (`tap`) e pelo script gerado (`_free_point`, mesma regra).
- **Validação:** 74 testes automáticos (4 novos). O script gerado de novo passou 3/3 no emulador; nas três o aviso "centro … tapado … a tocar em (226, …)" mostrou a deteção a atuar.
- **Pendente:** validar no emulador a mesma regra no agente (`tap`). O servidor Appium 4723 do utilizador estava ligado.

## 18. Prompt e3 — sem vocabulário de domínio (2026-11-13)

- **Observação:** as instruções pareciam feitas para as apps testadas. Não tinham nomes de apps, mas as regras e os exemplos refletiam os domínios delas: "payments, submissions or deletions" (PayU), "error message after submitting" (login da My Demo App), "carousel" (My Demo App), "{{testData.password}}". Faltava orientação para controlos que nenhuma app de teste tinha.
- **`EXECUTOR_E3` (por omissão):** só conceitos de interface Android.
  - Controlos: pickers, drop-downs, switches, check boxes, tabs, pagers horizontais, teclado a tapar campos.
  - Pop-ups não relacionados com o passo: onboarding, consentimento, avaliação/atualização, anúncios, permissões, notificações.
  - Conteúdo desenhado ou web embebido → `look_at_screen`.
  - `close_apps`.
  - Regras do veredicto sem exemplos de domínio: "nunca repetir uma ação que cria, envia, altera ou apaga dados"; `already_true_before_test` só quando a ação é impossível.
- **Também neutralizados:** as descrições do `swipe` ("horizontal pager" em vez de "carousel"); a contestação do WHEN ("o que o ecrã mostra depois, incluindo mensagens", em vez de "error message after submitting"); o exemplo `{{testData.<key>}}` na n2.
- **Teste novo** `test_default_prompts_and_llm_messages_have_no_domain_vocabulary`:
  - abrange as versões por omissão, as descrições das ferramentas e todas as mensagens do agente;
  - proíbe vocabulário de domínio (shop, cart, checkout, payment, order, product, price, bank, login, e-mail, password, carousel…);
  - uma fuga simulada ("payment") foi detetada.
- **Testes:** 76 automáticos. e1/e2 mantêm-se para reprodutibilidade. Custo: e3 ≈ 895 tokens contra 774 da e2 (+120 por chamada ao LLM).
- **Não validado no emulador** (sem novas execuções de teste).

## 19. Interfaces não expostas e ecrãs de teste genéricos (2026-11-13)

Requisito do projeto: o agente tem de funcionar com qualquer app nativa desconhecida, e as apps de teste não podem influenciar a implementação.

- **Ações num ponto da captura (`tap_point`, `long_press_point`).** Em interfaces desenhadas sem acessibilidade (superfícies gráficas, jogos, gráficos, conteúdo web embebido), o modelo via o conteúdo com `look_at_screen` mas só conseguia agir por ref.
  - Só funcionam depois de `look_at_screen` no mesmo passo.
  - A posição vem em pixels da captura, que é reduzida (`maxWidth 400`), e é convertida para o ecrã real pelo tamanho do PNG (cabeçalho IHDR, sem bibliotecas).
  - Se o ponto cair num controlo LISTADO e pequeno, a ação é recusada e o modelo é encaminhado para a ref (localizador estável).
  - Fica registado o nó mais interior nesse ponto (`screen.node_at`, mesmo que não seja listado), e o script gerado usa a verificação "ecrã diferente da gravação" antes de repetir o toque.
- **Ecrãs sintéticos** em `tests/data/generic/` (package `com.example.app`, 1080x2400):
  - formulário (campos, interruptor, caixa, lista suspensa, botão);
  - lista com itens iguais e botão flutuante;
  - diálogo sobre o conteúdo;
  - superfície desenhada + um botão.
  - `tests/test_generic_screens.py` (9 testes) cobre a leitura, contagens, elementos tapados, a conversão captura → ecrã (200,444 numa captura 400x889 → 540,1199 num ecrã 1080x2400), a recusa sem captura, fora da captura ou sobre um controlo listado, e o script gerado.
- **Testes:** 85 automáticos. Não validado no emulador (sem novas execuções de teste); o comportamento antigo não muda (as ferramentas novas só atuam quando o modelo as chama).

## 20. Arrastar e heurística independente da língua (2026-11-13)

- **`drag`** (agente): de um elemento (ref) ou posição da captura até outro elemento ou posição.
  - `hold=true` → premir, manter e mover (`appium_drag_and_drop`), para mover ou reordenar itens.
  - `hold=false` → mover diretamente (`appium_gesture` com início e fim), para sliders e desenho.
  - As posições seguem as regras do `tap_point`: exigem captura, são convertidas da captura para o ecrã, e um ponto de partida sobre um controlo listado é encaminhado para a ref.
  - Fica registado com o localizador da origem, o destino (localizador ou posição) e o modo.
  - O script gerado usa `drag(origem, destino, hold, expect)` com ações W3C de toque (premir, manter, mover, largar) e confirma o ecrã antes de arrastar a partir de uma posição.
  - `appium_drag_and_drop` passou a ser verificado no `/health`.
- **`package_matches_step`** (aviso de "package sem relação com a app pedida") deixou de usar palavras em português e inglês.
  - Compara palavras do passo (≥4 caracteres, qualquer alfabeto) com as partes do package.
  - Ignora apenas partes técnicas de packages (`com`, `org`, `android`, `app`…).
  - É só um aviso: um falso positivo apenas o suprime.
- **Testes:** 95 automáticos (10 novos).
  - Arrastar elemento → elemento (lista genérica), posição → posição numa superfície desenhada (100,444 → 300,444 numa captura 400x889 = 270,1199 → 810,1199 no ecrã), e recusa sem origem.
  - Heurística com passos em inglês, português, francês, alemão e chinês + inglês.
  - Não validado no emulador (sem novas execuções de teste).
