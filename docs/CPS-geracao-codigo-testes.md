# CPS — Geração de código / testes reutilizáveis a partir das execuções do QAgent

> Método: `Prompts/CPS.md` (Recuenco — Singular Solving, Cynefin, Systems Thinking, TRIZ, matriz ponderada).
> Data: 2026-11-12. Estado: **análise para decisão** — nada implementado.
> Fontes observadas: `genai_fastapi/agent.py`, `genai_fastapi-analise.md` (§10, §11, §12, §28), `appium-mcp` 1.99.3 (`tools/test-generation/generate-tests.js`), `Prompts/CPS-QAgent.md` (§3.1, §7.10, §7.11, Anexo A #8), código e execuções do QAgent.

## 1. Resumo executivo

Pediu-se que o QAgent "gere código de testes", como o appium-mcp e o genai_fastapi fazem para web. A análise mostra que o pedido declarado (código) é provavelmente um **meio**; a necessidade de fundo é **transformar uma execução autónoma bem-sucedida num teste reutilizável, determinístico e barato de repetir**, integrável no testingOn. O testingOn já tem execução mobile por *keywords*, Objects com identificador MOBILE e geração de código (Selenium/Playwright/Robot) no fluxo web. Gerar mais um formato de código no QAgent pode duplicar capacidades existentes.

**Recomendação:** criar no QAgent uma **representação canónica do teste executado** ("teste compilado": passos estruturados com locators estáveis, valores e asserções) com **replay determinístico sem LLM**; o código (ex.: Python + Appium) e os passos *keyword*/Objects do testingOn passam a ser **projeções** dessa representação. Antes de implementar: confirmar **quem consome o resultado e em que formato** (pergunta na secção 11) e aprovar a **alteração de âmbito** (CPS-QAgent 7.11 exclui geração de código).

## 2. Definição do problema

> Precisamos de **reutilizar uma execução autónoma bem-sucedida como teste de regressão repetível** (código e/ou teste do testingOn), no contexto de um **agente LLM agnóstico à app que escolhe o caminho em tempo de execução**, apesar de **o caminho não ser determinístico, haver conteúdo dinâmico, várias apps, passos humanos e segredos**, garantindo **fidelidade ao que foi executado, ausência de segredos nos artefactos, custo de repetição ≈ 0 tokens e compatibilidade com o testingOn**, porque **executar sempre com LLM é mais lento, caro e não determinístico para regressão**.

| | |
|---|---|
| **Problema declarado** | "O QAgent devia gerar código de testes (como o Appium/genai_fastapi)" |
| **Problema provável** | Uma execução LLM bem-sucedida morre no relatório: não há forma de a **repetir** sem LLM nem de a **transformar em ativo** do testingOn (teste *keyword* + Objects) ou de um repositório de código |
| **Stakeholders** | QA (quer regressão repetível e evidência), equipa testingOn (formato de teste/Objects, "Generate Test TestingON", Framework Repo), equipa GenAI/genai_fastapi (coerência com o web), gestão (custo LLM por execução) |
| **Critérios de sucesso** | Fidelidade (o artefacto reproduz o caminho que passou); repetição sem LLM; zero segredos em claro; integrável no testingOn; manutenção baixa |

## 3. Classificação (Cynefin)

**Complicado**, com uma parte **complexa**:
- *Complicado:* gerar código/representação a partir de ações registadas é engenharia conhecida (templates, mapeamento de ações).
- *Complexo:* se o artefacto gerado é **estável em repetição** depende da app (conteúdo dinâmico, animações, estado, várias apps) — só se sabe experimentando.

**Abordagem:** análise + comparação de alternativas para o desenho; **experiência pequena e reversível** para validar a estabilidade do replay antes de investir em formatos.

## 4. Diagnóstico

### 4.1 Factos (observados)
| # | Facto | Fonte |
|---|---|---|
| F1 | `appium_generate_tests` **não gera código**: devolve instruções para um LLM executar o cenário e depois escrever um teste "Appium/WebdriverIO-style", com waits explícitos | `generate-tests.js` |
| F2 | genai_fastapi `generate_selenium_test`: **o LLM escreve** um script **Selenium Python** standalone (waits, `sleep(1)` entre passos, prioridade id>name>class>CSS>XPath) a partir de `testCase` + `extracted_content` + `model_actions()`; gravado como está em `scripts/<recordId>.py` | `agent.py` |
| F3 | No genai_fastapi o script é gerado **em todas as execuções** (também as falhadas), o `recordId` é o ".webm mais recente" (concorrência), `/selenium-script/{id}` **não exige API key**, apaga o ficheiro após download, `llm.invoke` síncrono em `async` | análise §11, §12, §28 |
| F4 | `generate_playwright_test`, `capture_objects` (Page Objects), `generate_gherkin`, `generate_test_report` existem mas **não são usados** | `agent.py`, análise §28.6 |
| F5 | testingOn: testes = **passos *keyword*** + **Objects** (identificador WEB e **MOBILE**); **execução mobile por *keywords* já existe**; Record & Play Mobile; GenAI "Custom Autonomous Execution" → *keywords* → execução → **código Selenium/Playwright/Robot** → "Generate Test TestingON" | CPS-QAgent §3.1 |
| F6 | O contrato JSON dos passos *keyword* do testingOn **é desconhecido** | CPS-QAgent Anexo A #8 |
| F7 | Geração de código e exportação para Framework Repo estão **fora de âmbito** do protótipo | CPS-QAgent §7.11 |
| F8 | O QAgent regista, por passo, **ações bem-sucedidas com locators estáveis** (accessibility id > id > texto; frágeis marcados) e já **executa passos estruturados determinísticos** (F4) | `result.json`, `executor.py` |
| F9 | **Lacuna:** as ações registadas **não guardam o valor** (texto escrito como template, texto lido, condições de espera completas); passos `ai` com coordenadas, `open_app`, `human_input`, `resetApps` não têm equivalente direto nos passos estruturados atuais | `ai_executor.py`, `models.py` |

### 4.2 Hipóteses (por validar)
| # | Hipótese | Evidência que a confirma/rejeita |
|---|---|---|
| H1 | O consumidor real é o **testingOn** (teste *keyword* persistido), não um repositório de código Python | Decisão tomada (secção 11) |
| H2 | Um teste "compilado" a partir de uma execução que passou **repete-se com ≥ 90 %** de sucesso na mesma versão da app | Experiência: 10 replays por caso, 3+ apps |
| H3 | Código gerado por LLM (estilo genai_fastapi) **diverge** do caminho executado com frequência relevante | Comparar script LLM vs ações registadas em N execuções |
| H4 | A equipa tem/terá um **servidor Appium** para correr scripts fora do QAgent | Confirmar com QA/testingOn ("Appium Version" nos Devices sugere que sim) |

### 4.3 Causas do problema provável (Five Whys, resumido)
Porque não se reutiliza uma execução? → só existe relatório. → Porque o relatório guarda ações para leitura humana, não um modelo executável completo (F9). → Porque o desenho priorizou evidência (CPS 7.5) e não reprodução. → Causa sistémica: **falta um formato canónico de "teste" no QAgent** a partir do qual se possa repetir e exportar.

## 5. Visão sistémica

```
            (LLM, 1×)                     (sem LLM, N×)
 NL/Gherkin ──► Execução QAgent ──► Teste compilado (canónico) ──► Replay QAgent (regressão)
                                          │
                                          ├──► Script Python + Appium (projeção)
                                          ├──► Passos keyword + Objects MOBILE (projeção → testingOn, requer F6)
                                          └──► (futuro) Robot / Java / WebdriverIO (projeções)
```

- **Upstream:** qualidade do caminho escolhido pelo LLM; locators (frágeis = risco de replay).
- **Downstream:** testingOn (Objects, *keywords*, Generate Test, Framework Repo, Self-Healing), CI de quem corre scripts.
- **Efeitos de 2.ª ordem:** com replay barato, o LLM passa a ser usado só para **criar** e **reparar** testes (self-healing), reduzindo custo e variância. Risco: testes compilados envelhecem quando a app muda → precisa de política de "re-compilar".
- **Segurança:** artefactos exportados não podem conter segredos (template + variáveis de ambiente), endpoints protegidos (contrário a F3).

## 6. Alternativas

| | **A. Código por LLM** (como genai_fastapi / appium-mcp) | **B. Código determinístico** a partir das ações registadas | **C. Teste compilado canónico + replay + projeções** | **D. Adiar para a F7** (definir com testingOn primeiro) |
|---|---|---|---|---|
| Descrição | Prompt com caso + ações → LLM escreve script Python/Appium | Template por linguagem que traduz cada ação registada em código | Converter a execução em passos estruturados completos (locator, valor, espera, asserção); replay no QAgent; código e *keywords* como exportadores | Não implementar agora; levar a questão ao mapeamento de integração |
| Benefícios | Rápido de fazer; coerente com o web; código "legível" | Fiel ao executado; 0 tokens; previsível | Fiel; 0 tokens no replay; **um modelo serve vários formatos** (código, testingOn, futuros); base para self-healing | Evita retrabalho se o formato do testingOn for diferente |
| Custos/esforço | Baixo | Médio (mapeamento + template) | Médio-alto (modelo canónico + replay + 1.º exportador) | Nulo agora |
| Riscos | Alucina/omite passos (H3); custo por execução; não verificável sem correr | Acoplado a uma linguagem; repetir trabalho por formato | Maior desenho inicial; conteúdo dinâmico pode partir replays | Perde-se a evidência de valor até à F7 |
| Reversibilidade | Alta | Alta | Média (o formato canónico passa a ser contrato) | Total |
| 2.ª ordem | Repete os problemas F3 se copiado | Cada novo formato = novo gerador | Habilita "Generate Test TestingON" mobile e self-healing | — |
| Evidência para validar | H3 | Executar o script gerado no emulador | H2 + executar o script exportado | H1 |

**Contradição (TRIZ):** queremos **autonomia/adaptação (LLM)** *e* **determinismo/custo zero (regressão)**. Princípio de **separação no tempo**: LLM na **criação** (e reparação), execução determinística na **repetição**. A alternativa C resolve a contradição em vez de escolher um dos lados; A e B só produzem código, sem replay no QAgent.

## 7. Recomendação

**C**, com o primeiro exportador **Python + Appium-Python-Client** (B como projeção, no mesmo estilo do script Selenium do genai_fastapi: standalone, waits explícitos, pausa de 1 s) **apenas se** houver um consumidor de código confirmado; o exportador para **passos *keyword* + Objects** fica dependente do contrato do testingOn (F6).

### Matriz de decisão (pontuação 1–5 subjetiva, justificada acima; pesos = 100 %)

| Critério | Peso | A | B | C |
|---|---|---|---|---|
| Fidelidade ao executado | 30 % | 2 | 5 | 5 |
| Reutilização / integração testingOn | 20 % | 3 | 3 | 5 |
| Custo por repetição (tokens) | 15 % | 2 | 5 | 5 |
| Esforço de implementação | 15 % | 5 | 3 | 3 |
| Coerência com genai_fastapi | 10 % | 5 | 4 | 3 |
| Segurança (segredos, endpoints) | 10 % | 3 | 4 | 5 |
| **Total ponderado** | 100 % | **3,05** | **4,10** | **4,50** |

- **Rejeitada A** como solução principal: fidelidade baixa (o código descreve o que o LLM *acha* que aconteceu) e custo por execução; pode voltar como "polimento" opcional (nomes, comentários) sobre o código determinístico.
- **D** não é rejeitada: se a resposta à pergunta da secção 11 for "o consumidor é só o testingOn e o formato ainda não é conhecido", fazer **apenas** o núcleo de C (teste compilado + replay), que tem valor próprio, e adiar exportadores.
- **Pressupostos:** H1/H2; a execução mobile do testingOn aceita locators accessibility id/id/UiSelector (o Inspector expõe-nos — F5).
- **Deixa de ser válida se:** o testingOn já tiver/pretender um gerador de código a partir dos seus passos *keyword* (então o QAgent só precisa de exportar *keywords* + Objects); ou se o replay compilado se mostrar instável (H2 falhar) — aí o valor passa para self-healing com LLM em cada execução.

## 8. Plano de ação

| # | Ação | Responsável sugerido | Prioridade | Sequência | Dependências | Resultado esperado | Critério de conclusão |
|---|---|---|---|---|---|---|---|
| 0 | **Decisão:** alterar o âmbito (CPS-QAgent 7.11) e responder à pergunta da secção 11 | Utilizador (+ testingOn) | Crítica | 1 | — | Consumidor e formato definidos | Decisão registada no CPS |
| 1 | Registar **valores** nas ações (template do texto escrito, texto lido, condição de espera, app aberta, passo humano) | Dev QAgent | Alta | 2 | 0 | `result.json` suficiente para reproduzir | Teste unitário: todas as ações têm o necessário |
| 2 | **Compilar** execução → passos estruturados completos (`GET …/compiled`), sem segredos | Dev QAgent | Alta | 3 | 1 | Teste canónico | 0 segredos; passos frágeis sinalizados |
| 3 | **Experiência H2:** replay determinístico (10×) de testes compilados em 3+ apps (My Demo, Relógio/Contactos, eShop) | Dev QAgent | Alta | 4 | 2 | Taxa de replay | ≥ 9/10 por caso, ou causas classificadas |
| 4 | Exportador **Python + Appium** (se o 0 o confirmar) | Dev QAgent | Média | 5 | 2 (e 3 para confiança) | `test_<id>.py` executável | Script corre no emulador contra um servidor Appium e passa |
| 5 | Endpoint protegido + botão "Generate" no ecrã (download; sem apagar após download) | Dev QAgent | Média | 6 | 2/4 | Uso pelo QA | E2E no browser |
| 6 | Exportador **keyword + Objects** testingOn | Dev QAgent + testingOn | Média | F7 | Contrato F6 | Teste importável | Import bem-sucedido no testingOn |

Classificação: **decisão** (0); **diagnóstico/validação** (3); **construção** (1, 2, 4, 5, 6); **preventivas** (segredos fora dos artefactos, endpoints protegidos, sem "ficheiro mais recente").

## 9. Riscos e contingência (pre-mortem: "o código gerado não serviu para nada")

| Razão provável | Prob. | Impacto | Mitigação / sinal de alerta |
|---|---|---|---|
| Ninguém consome o formato gerado (consumidor era o testingOn) | Média | Alto | Ação 0 antes de qualquer exportador |
| Replays partem por conteúdo dinâmico (preços, timers), animações ou estado | Média | Alto | H2 primeiro; locators frágeis sinalizados; `resetApps`; esperas por texto em vez de sleeps |
| Coordenadas / `UiSelector().instance(n)` no caminho | Média | Médio | Marcar o teste compilado como "frágil"; avisar no export |
| Passos humanos (login) | Alta em apps reais | Médio | No replay: pausa `manual`; no script: `input("…Enter para continuar")` |
| Segredos no código | Baixa (por desenho) | Alto | Templates + `os.environ`; teste automático de ausência de segredos |
| Equipa sem servidor Appium para correr scripts | Média | Médio | Replay no QAgent continua a funcionar; documentar arranque do Appium |
| App muda e testes compilados envelhecem | Alta (com o tempo) | Médio | Re-compilar com LLM quando o replay falha (self-healing, fase futura) |

Condições: **continuar** se H2 ≥ 90 %; **ajustar** (marcar frágeis / re-compilar) se 70–90 %; **parar exportadores** e manter só relatório + LLM se < 70 %.

## 10. Métricas de sucesso

- Taxa de sucesso do replay compilado (mesma versão da app): ≥ 90 %.
- Tokens no replay: 0. Tempo de replay vs execução LLM (esperado: bem inferior).
- Scripts exportados que correm sem edição manual: ≥ 90 % dos testes compilados estáveis.
- Segredos em artefactos: 0.
- (Integração) testes importados no testingOn sem correção manual.

## 11. Próxima ação — pergunta que decide o desenho

**Quem vai consumir o resultado e em que formato?**
1. **O testingOn** (guardar como teste *keyword* + Objects MOBILE, e o próprio testingOn gera código/executa) → núcleo C + exportador *keyword* (precisa do contrato, F6).
2. **QA/CI fora do testingOn** (repositório de código) → núcleo C + exportador de código; indicar linguagem/framework (Python+Appium como o Selenium do genai_fastapi? Java? Robot?).
3. **Ambos / ainda não se sabe** → núcleo C (teste compilado + replay no QAgent) agora; exportadores depois.

## 12. Decisão (2026-11-12)

- **Consumidor:** QA / CI **fora do testingOn** (repositório de código). **Linguagem:** **Python + Appium-Python-Client**, script standalone no estilo do Selenium do genai_fastapi (waits explícitos, pausa de 1 s entre passos, executável com `python script.py`). Âmbito alargado face ao CPS-QAgent §7.11 por decisão do utilizador.
- **Ajuste ao plano:** o **próprio script gerado** é o mecanismo de repetição sem LLM nesta fase — a experiência H2 passa a ser "executar o script gerado N vezes no emulador" (servidor Appium 3.9.0 + UiAutomator2 8.7.3 já presentes em `tools/appium-mcp/node_modules`). Um motor de replay dentro do QAgent fica para quando houver consumidor (ex.: testingOn).
- Geração **determinística** a partir das ações registadas (opção B/C), sem LLM; segredos como variáveis de ambiente; endpoint protegido por `X-API-Key`; o ficheiro não é apagado após download.

## 13. Resultado da implementação e da experiência H2 (2026-11-12)

**Construído:** `src/qagent/codegen.py` (gerador determinístico, sem LLM), `GET /mobile/testExecution/{id}/script` (protegido, 409 se não terminou/cancelada, recusa se encontrar um segredo, ficheiro guardado como artefacto e não apagado), botões **Generate** (download) e **Preview** no ecrã, `scripts/start-appium-server.ps1` (Appium 3.9.0 + UiAutomator2 8.7.3 já presentes, só 127.0.0.1), registo de `value` nas ações (template do texto escrito, texto lido mascarado, timeout de esperas) e de `app_switched`. Testes: `tests/test_codegen.py` (19 no total).

**H2 — scripts gerados executados no emulador contra o servidor Appium (medição final):**

| Origem (execução) | Tipo | Resultado |
|---|---|---|
| `ce3fe23922ee` | CA2, texto livre | ✅ 3/3 |
| `b33b259fc42c` | Passos estruturados | ✅ 3/3 (+1 execução pendurada por bloqueio do emulador, excluída) |
| `faab52511e74` | eShop (caso manual) | ✅ 3/3 |
| `a1656d337030` | Várias apps (Relógio + Contactos) | ❌ 0/3 |

**Defeitos do gerador encontrados e corrigidos durante a experiência (todos genéricos):** `scroll_to` traduzido como `scroll('to')`; abrir uma app tocando num ícone do launcher (dependente da posição) → convertido em `open_app(package)` (o executor regista `app_switched`); arranque a frio na 1.ª abertura de cada app (o eShop reabria no carrinho); ecrãs do sistema (permissões) nunca passam a "app esperada"; diálogos de permissões aceites pelos ids standard do Android; a recuperação de interrupções feita pelo agente não é reproduzida literalmente (o `ensure_app()` trata interrupções na repetição); passos manuais (`human_input`) → `input("… Enter para continuar")`.

**Limites confirmados:**
1. **Interrupções que não mudam a app em primeiro plano** (ex.: notificação *heads-up* do alarme a tapar o botão Save) não são detetáveis pelo script determinístico; o agente LLM via-as e reagia. O caso multi-app tem esta corrida embutida (temporizador de 10 s a disparar durante a criação do contacto) → 0/3.
2. **Verificações semânticas do LLM** (contar, comparar) passam a verificações de presença/texto; "valida quantos produtos" não gera uma asserção de contagem.
3. **Locators frágeis** (coordenadas, `instance(n)`, texto dinâmico, sugestão de campos editáveis) são sinalizados com ⚠ no código.
4. **Ambiente:** servidor Appium e QAgent **não podem correr ao mesmo tempo no mesmo emulador** (conflito do servidor UiAutomator2 e `adb` sem resposta); com RAM do PC no limite (≈ 0,6 GB livres) o emulador bloqueou e teve de ser reiniciado.

**Conclusão:** H2 confirmada para casos de uma app sem interrupções temporais (9/9 em 3 scripts de origens diferentes); não confirmada para cenários com interrupções de outras apps durante a ação. Condição do §9: "continuar" para o caso comum; os casos com corridas temporais ficam como limitação documentada (o próprio caso de teste é instável por desenho).
