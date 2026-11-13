# F3 — Registo: caso completo em linguagem natural + relatório — ✅ CONCLUÍDA (2026-11-12)

> Referência: `Prompts/CPS-QAgent.md`, secções 7.1, 7.2, 7.4, 8 (F3) e 9.3. LLM: Azure OpenAI (deployment GPT-5.1).

## 1. Resultado

**Critério do CPS:** CA2 e CA3 cumpridos, fora da API e pela API.

| CA | Execução | Resultado |
|---|---|---|
| **CA2**: login válido em **texto livre** | `runs/1449e8f4e0c1` (antes das correções) e `runs/d831604ae798` | ✅ `passed`. O LLM dividiu o texto em **6 passos** (When ×5, Then ×1); 6/6 com `status`, `reason`, screenshot e locators (accessibility id / id / uiautomator; **0 xpath**); `summary` "6/6 passos passaram." Última: 47 s, 14 chamadas LLM, 20 670 tokens in / 601 out |
| **CA3**: utilizador bloqueado em **Gherkin** | `runs/2f1a06996283` | ✅ `failed` **no passo de validação**: `Then é apresentado o catálogo` → *"O catálogo de produtos não foi apresentado. A tela permanece no login e exibe a mensagem de erro: 'Sorry this user has been locked out.'"* (locator `id/passwordErrorTV`); `And …Log Out` → `skipped`; Given/When `passed`. 43 s, 10 chamadas, 18 161 / 420 tokens |
| Segredos | as 4 execuções | password e chave Azure: **0** ocorrências nos ficheiros |

Tentativa falhada pelo caminho (`runs/7a9b3154c113`): o `Given` falhou porque o modelo não viu o "Log In" do menu e concluiu que não existia (ver 3.1).

## 2. O que foi construído

| Componente | Descrição |
|---|---|
| `src/qagent/normalizer.py` | **Gherkin → passos** determinístico, sem LLM (CPS 7.4). AND/BUT herdam o tipo efetivo do passo anterior. **Texto livre → passos**: 1 chamada `with_structured_output(NormalizedCase)` (Pydantic, máx. 15 passos). O LLM recebe só os nomes dos placeholders de testData |
| Grafo **LangGraph** (`orchestrator.build_graph`) | `START → normalize → execute_step ⟲ → END`. `normalize` só atua em texto livre; `execute_step` aplica timeout, `stopOnFailure`, evidências e deteção de ANR. O ReAct do LLM fica **dentro** do nó (`AiStepExecutor`). A sessão Appium e a limpeza ficam **fora** do grafo (garantia de `delete` em erro/stop) |
| Executor (`ai_executor.py`) | Entende `[GIVEN]` (garante a pré-condição), `[WHEN]` (passa quando a ação foi feita; o resultado é verificado pelo Then), `[THEN]` (verificação explícita; em falha, cita o que o ecrã mostra). É isto que coloca a falha do CA3 no Then |
| API | Texto livre e Gherkin deixam de dar 501; exigem LLM (400 sem cabeçalhos). Precedência: `steps` > `scenario` > `testExecution`. Métricas incluem a chamada do normalizador |
| Frontend | Separadores **Manual test steps** e **Gherkin** funcionais, com campo **Test data (JSON)** (vazio por omissão) |
| `examples/` | `ca2-texto-livre-login.json`, `ca3-gherkin-bloqueado.json` |
| `scripts/run_case.py` | Envia um exemplo à API com o LLM das variáveis de utilizador (chave só no cabeçalho, nunca impressa) e mostra o relatório |
| Testes | 14 (API + normalizador com LLM simulado) |

## 3. Problemas encontrados e corrigidos

1. **Resumo do ecrã cortava o menu:** com o menu aberto, os produtos por trás (5 estrelas sem rótulo cada) enchiam o limite de 40 elementos e os itens do menu ficavam de fora. Agora são descartados os elementos sem texto, sem descrição e sem id, e as repetições acima de 2; o resumo termina com "lists and menus may continue below — use scroll_to".
2. **Ecrã lido durante a animação:** depois de um `tap`, o ecrã é relido até mudar (até ~2,5 s).
3. **Prompt:** obrigatório fazer `scroll_to` antes de concluir que um elemento não existe.

Efeito no CA2: de 26 223 para 20 670 tokens de entrada (−21 %) e de 59 para 47 s.

## 4. Pendentes / para a F5

- A execução pelo **ecrã** dos separadores Manual/Gherkin foi validada só por *typecheck*; o mesmo pedido foi validado pela API. Falta um ensaio manual no browser.
- Medir estabilidade (CA5: 10 execuções do CA2) e custo médio (CA6), e a % de locators (CA7).
- O normalizador às vezes divide em mais passos do que o necessário (6 para um login; ex.: "Abre o menu" e "Entra no ecrã de Log In" separados). Funciona, mas custa chamadas. Avaliar na F5.
