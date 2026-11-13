# F2 — Registo: executor de passo com LLM — ✅ CONCLUÍDA (2026-11-12, Azure OpenAI 5/5)

> Referência: `Prompts/CPS-QAgent.md`, secções 7.1 (Executor de passo), 7.6, 8 (F2). Provider de ponte: **Gemini** (*free tier*).

## 00. Resultado final (2026-11-12): **PASSOU com Azure OpenAI → F2 CONCLUÍDA**

**Critério:** ≥ 4/5 tentativas, tokens medidos. **Resultado: 5/5** (`runs/f2/20261112-104502`), deployment GPT-5.1 no Azure OpenAI da empresa (endpoint, deployment e versão indicados pelo utilizador; chave em variável de utilizador do Windows).

| Métrica (2 passos NL: login + validar catálogo) | Valor |
|---|---|
| Sucesso | **5/5**, 0 ANRs |
| Chamadas LLM por tentativa | **6** (estável nas 5) |
| Tokens por tentativa | **≈ 10 142 in / 316 out** |
| Tempo por tentativa | 33–40 s (média 35,6 s, incluindo criação da sessão e pré-condição) |
| Locators usados | `accessibility id` 20, `id` 10, **xpath 0** |
| Segredos | password e chave Azure: 0 ocorrências nos ficheiros |

**Execução completa pelo ecrã** (`runs/e2c1852c1445`, 3 passos `ai`: abrir menu/Log In, login, validar): `passed` 3/3, 61 s, 13 chamadas, 32 220 tokens in / 859 out. O passo "abre o menu e entra no Log In" sozinho custou 22 k tokens (menu longo, item fora do ecrã) → candidato a otimização na F5.

**Compatibilidade:** `langchain-openai` 0.3.1 (versão do genai_fastapi) funciona com o GPT-5.1 via Chat Completions, desde que não se envie `temperature` (modelo de raciocínio). `is_reasoning_model()` trata disso pelo nome do deployment.

**Comparação com o Gemini (`gemini-2.5-flash`, *free tier*):** 1 tentativa válida (8 chamadas, 16 k tokens, 62 s) antes de esgotar a quota de 20 pedidos/dia/modelo. Com o Azure: menos chamadas (6), menos tokens (10 k) e mais rápido (36 s). Primeira evidência para o CA10.

## 0. Atualização 2026-11-12 — Gemini real: **funciona, mas a quota gratuita bloqueia o critério**

| Tentativa (`runs/f2/20261112-094948`, `gemini-2.5-flash`) | Resultado |
|---|---|
| Ensaio antes da correção (`runs/f2/20261112-094618`) | ❌ login feito em 3 ações, mas na verificação o modelo **inventou** `accessibility id = "Products"` e repetiu-o 5× → `maxActionsPerStep` excedido |
| Ensaio logo após *cold boot* do emulador (`runs/f2/20261112-094343`) | ❌ ANR da app (igual à F0); o modelo detetou-o corretamente ("My Demo App isn't responding") e marcou `failed` |
| **1** (após a correção abaixo) | ✅ 2/2 passos, **8 chamadas LLM, 16 244 tokens in / 254 out, 62 s**. Locators: `id` ×2, `accessibility id` ×3. Repetiu o locator inventado 1×, recebeu o ecrã real e usou `accessibility id = title` |
| 2–5 | ⛔ `429 RESOURCE_EXHAUSTED`: **`GenerateRequestsPerDayPerProjectPerModel-FreeTier = 20`**, `retryDelay` ≈ 22 h |

**Correção ao executor (2026-11-12):** depois de `tap`/`press_back`, a resposta da ferramenta inclui o ecrã novo; quando um elemento não é encontrado, inclui o ecrã atual ("do not invent locators"); a repetição exata de uma chamada que já falhou é rejeitada.

**Quota do *free tier* (medida na própria API, não em blogs):** 20 pedidos/dia **por modelo** e por projeto. Cada tentativa F2 (2 passos) ≈ 8 pedidos → **≈ 2 tentativas/dia/modelo**; um login de 3 passos `ai` pela API ≈ 10–12 pedidos. Outros modelos têm quota própria (`gemini-flash-lite-latest` e `gemini-3.5-flash-lite` responderam 200 após o esgotamento do 2.5-flash). `gemini-2.5-flash-lite` → 404 (já não existe).

**Chave:** formato novo (53 caracteres, não começa por `AIza`); validada por listagem de modelos (48 com `generateContent`).

## 1. Estado (2026-11-11): **CONSTRUÍDO — critério por medir (falta a chave Gemini)**

**Critério do CPS:** passo executado em ≥ 4/5 tentativas; tokens medidos.

| Verificação | Resultado |
|---|---|
| Ciclo completo com **LLM simulado** (guião programado), emulador real | ✅ 2/2 passos NL `passed`, 6 chamadas LLM, ações e locators registados (`id`/`accessibility id`), 21 s (`runs/f2/20261111-205439`) |
| Password fora de logs/resultados | ✅ o LLM só vê `{{testData.password}}`; valor substituído na ferramenta; 0 ocorrências nos ficheiros |
| API: passos `ai` sem cabeçalhos LLM | ✅ 400 com mensagem clara; chave LLM nunca gravada em disco (teste unitário) |
| **Gemini real, 5 tentativas** | ⏳ por executar: `python scripts/f2_step.py --provider gemini --attempts 5` |

## 2. Desenho

- **Passo `ai`** no contrato (`{"action": "ai", "text": "<instrução>"}`), misturável com passos estruturados. O texto livre sem passos continua a dar 501 até haver o normalizador (F3).
- **ReAct limitado a um passo** (`AiStepExecutor`): o LLM recebe o passo, os *placeholders* de testData e o **resumo do ecrã**, chama ferramentas e termina com `finish_step(passed|failed, reason)`. Limites: `maxActionsPerStep` (8 por omissão), timeout de passo de ≥ 180 s (inclui o *backoff* de 429).
- **Ferramentas compactas** (8): `get_screen`, `tap`, `type_text`, `read_text`, `check_visible`, `scroll_to`, `press_back`, `finish_step`. Usam o `StructuredExecutor` da F4 por baixo (`sessionId` explícito, espera ativa, registo de ações e locators). ≈ 0,7k tokens de definições contra ≈ 11k das definições MCP em bruto. Desvio deliberado da *allowlist* MCP direta do CPS 7.7, para poupar quota do *free tier*.
- **Resumo do ecrã:** `generate_locators` → 1 linha por elemento com o locator preferido (accessibility id > id > uiautomator > xpath), no máximo 40 elementos.
- **Salvaguardas:** `passed` é rejeitado se ainda não houve nenhuma ação ou verificação bem-sucedida (CPS 7.6); o *prompt* obriga a verificar com `read_text`/`check_visible` nos passos de validação.
- **Fábrica de LLM** (`src/qagent/llm.py`): `gemini` (`ChatGoogleGenerativeAI`, `temperature=0`, `max_retries=4`), `azure` (`AzureChatOpenAI`) e `fake`. Escolhida por `X-Provider`, `X-LLM-Model`, `X-LLM-API-Key`, `X-LLM-Endpoint` e `X-LLM-APIVersion`. A chave entra na lista de valores mascarados.
- **Frontend:** "Gemini" ativo no GenAI Server (modelo por omissão `gemini-2.5-flash`); exemplo "Login — natural language (AI)" (`examples/login-ia.json`, 3 passos `ai`).
- A F3 vai envolver isto num grafo LangGraph. Na F2 o ciclo é manual (`bind_tools`) para controlar a injeção do `sessionId`, os *placeholders* e a contagem de tokens.

## 3. Descoberta

- **Corrida após transições:** `scroll_to_element` logo a seguir a abrir o menu falha com "page source did not change". Pela API não acontecia, porque o page source entre passos dava o tempo necessário. Corrigido no executor: 2 tentativas com 1 s de intervalo.

## 4. Riscos a confirmar com a chave

1. **`langchain-google-genai` 2.1.0** (fixado pelo genai_fastapi) é anterior aos modelos Gemini mais recentes. Não expõe o controlo de *thinking* e pode não tratar as *thought signatures* exigidas por modelos novos em chamadas de ferramentas com várias voltas. Se falhar: usar um modelo suportado (ex.: `gemini-2.5-flash`) ou subir a versão, o que obriga a subir o `langchain-core` (conflito com o genai_fastapi, F1-registo 3).
2. Quota do *free tier*: cada tentativa do teste F2 ≈ 4–8 chamadas; 5 tentativas ≈ 20–40 pedidos.
