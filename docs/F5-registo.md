# F5 — Registo: robustez e custo — ✅ CONCLUÍDA (2026-11-12)

> Referência: `Prompts/CPS-QAgent.md`, secção 8 (F5) e 9.3 (CA5–CA7). LLM: Azure OpenAI (deployment GPT-5.1). Caso: CA2 em texto livre (`examples/ca2-texto-livre-login.json`). Script: `scripts/f5_batch.py`.

## 1. Resultados (10 execuções seguidas cada)

| Métrica | Base (`runs/f5/20261112-114749-baseline`) | **Otimizado** (`runs/f5/20261112-115858-optimized`) | Variação |
|---|---|---|---|
| **CA5:** `passed` | 9/10 ✅ | **10/10** ✅ | +1 |
| Passos por execução | 5 | **3** | −40 % |
| Chamadas LLM (média) | 16 | **11** | −31 % |
| **CA6:** tokens de entrada (média) | 49 411 | **29 239** | **−41 %** |
| Tokens de saída (média) | 746 | **478** | −36 % |
| Duração (média) | 63,1 s | **45,8 s** | −27 % |
| Chamadas de ferramentas (média) | 44 | 33 | −25 % |
| **CA7:** locators bons (accessibility id / id / uiautomator) | 100 % | **100 %** ✅ | — |
| xpath absoluto | 0 | 0 | — |

Custo indicativo (tabela pública GPT-5.x ≈ 1,25 $/M entrada, 10 $/M saída; **confirmar com o contrato Azure**): ≈ 4 cêntimos por execução otimizada (≈ 6 na base), antes do desconto de *prompt caching*.

## 2. Falhas (CA5 pede classificação: app / ambiente / LLM / appium-mcp)

| Execução | Categoria | Causa | Estado |
|---|---|---|---|
| Base #7 (`1b0416c59856`) | **LLM / normalizador** | O normalizador dividiu o login em "utilizador" e "password"; o agente fez o login completo no 1.º passo e o 2.º já não encontrou o campo (devia ter declarado `already_done_by_step`) | Corrigido: um passo por objetivo |

## 3. Otimizações

1. **Compactação do histórico do passo:** cada ação devolve o ecrã completo e os anteriores ficavam todos na conversa com o LLM. Agora só o ecrã mais recente fica completo; os anteriores passam a "[earlier screen description omitted — refs … no longer valid]" (as refs mudam a cada ecrã, por isso o conteúdo antigo era também enganador).
2. **Normalizador: um passo por objetivo ou mudança de ecrã**, não por micro-ação ("preencher e submeter um formulário é UM passo"; cada resultado esperado continua num Then próprio). Menos passos significa menos arranques de passo (cada um envia o *prompt*, as ferramentas e o ecrã completo) e elimina a classe de falha da base #7.
3. O *prefixo* de cada chamada (system prompt + definições de ferramentas) é estável → elegível para *prompt caching* do Azure (desconto, não menos tokens contados).

## 4. Regressão depois das otimizações

| Caso | Resultado |
|---|---|
| CA3 Gherkin, utilizador bloqueado (`8c6f2e78a7b5`) | ✅ `failed` no Then com "Sorry this user has been locked out.", And `skipped`; 21 k tokens |
| Várias apps, Relógio + Contactos, com `resetApps` incluindo contactos (`fb7d82893024`) | Passos 1–4 ✅ (temporizador, contacto criado e confirmado, regresso ao Relógio; 5 passos em vez de 8). Passo 5 ❌: o Then "o temporizador já terminou" foi lido como "não terminou" |

**Nota sobre o passo 5:** o screenshot mostra o temporizador expirado (−52 s, cartão destacado, botão parar), mas a **descrição de acessibilidade da própria app diz "50 seconds remaining"**. O modelo confiou nesse texto enganador. É uma ambiguidade do caso + da app, não uma regressão. Mitigações possíveis (não aplicadas): o agente usar `look_at_screen` quando a árvore e os valores visíveis se contradizem; casos de teste com o resultado esperado explícito ("o temporizador mostra tempo negativo / está a tocar").

## 5. Pendentes de custo

- O caso com várias apps continua caro (≈ 64 k tokens por 5 passos): a descrição do ecrã de apps densas (lista de produtos, menus) domina. Próximas reduções possíveis: omitir o conteúdo por trás de sobreposições (menus/diálogos), resumir itens repetidos de listas, limitar `MAX_ELEMENTS` por região.
- Medir o efeito real do *prompt caching* no Azure (*cached tokens* na resposta).
