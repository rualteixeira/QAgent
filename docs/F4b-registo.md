# F4b — Registo: frontend de teste "Mobile Autonomous Execution"

> Referência: `Prompts/CPS-QAgent.md`, secções 7.13 e 8 (F4b). Entrada: `docs/F4-registo.md`.

## 1. Resultado (2026-11-11): **PASSOU (modo estruturado) → CONTINUAR**

**Critério do CPS:** executar o CA2 de ponta a ponta pelo frontend: escolher dispositivo e app, escrever os passos, ver o progresso e os screenshots, fazer stop.

Verificado com um teste E2E automatizado (Playwright + Edge headless, fora do repositório):

| Verificação | Resultado |
|---|---|
| Dispositivo carregado de `GET /mobile/devices` | ✅ `emulator-5554 · EMULATOR · sdk_gphone64_x86_64` pré-selecionado |
| Texto livre ("Manual test steps") | ✅ a API responde 501; o ecrã mostra "Not available yet: … requer o executor com LLM" |
| Passos estruturados (exemplo "Login — valid user") | ✅ progresso "Executing step N of 9"; fim com **Passed**, 9 × "Executed", **9 miniaturas** de screenshot; métricas (26 s, 38 tool calls, 0 LLM) |
| Screenshot em grande | ✅ diálogo abre e fecha |
| Stop durante a execução | ✅ **Cancelled**; passo em curso "Interrompido pelo stop", restantes "Não executado (stop)" |
| Erros na consola do browser | Só o 501 esperado (o 404 do favicon foi corrigido depois) |

Ressalva igual à F4: o fluxo em linguagem natural e Gherkin só fica funcional com a F2/F3. Os separadores existem e enviam o pedido correto (`testExecution` / `scenario`).

## 2. O que foi construído (`frontend/`)

| Ficheiro | Papel |
|---|---|
| `src/App.tsx` | Ecrã único. **Cabeçalho:** seletor "GenAI Server" (provider/modelo/chave → `X-Provider`/`X-LLM-*`; só "None — structured steps" ativo até à F2). **Configuration:** plataforma (iOS desativado, F6), dispositivo (+ atualizar), app package/activity/APK, *stop on failure*, política de screenshots. **Entrada:** separadores "Manual test steps", "Gherkin" (texto → `scenario`), "Structured steps" (JSON com exemplos carregáveis). **Recent executions** (clicar reabre o relatório) |
| `src/components/ResultPanel.tsx` | Estado, progresso ao vivo, botão **Stop**, resumo, passos com estado/motivo/duração, **locators** por passo (xpath marcado como frágil), miniatura do screenshot, métricas, Generate/Preview/Save **desativados**, download de `result.json` e `qagent.log` |
| `src/components/Screenshot.tsx` | Miniatura + diálogo. A imagem é pedida com `X-API-Key` e mostrada por *blob URL* (um `<img src>` não envia cabeçalhos) |
| `src/api.ts` | Cliente HTTP (sem lógica de negócio); erros `{"detail"}` → mensagem legível |
| `src/types.ts`, `src/status.ts` | Contrato da API; rótulos ao estilo do testingOn (`passed` → "Executed", etc.) |

Os exemplos vêm diretamente de `../examples/*.json` (fonte única com a F4; `server.fs.allow: [".."]` no Vite).

**Stack:** React 19.3.1, MUI 9.5.0, Vite 8.3.8, TypeScript 7.0.2 (versões exatas no `package.json`). ⚠️ Confirmar as versões de React/MUI do frontend do testingOn antes de portar o componente (F7).

## 3. Como executar

```powershell
# API (ver docs/F4-registo.md) a correr em 127.0.0.1:8100, depois:
cd frontend
npm install
copy .env.example .env.local   # VITE_QAGENT_API_URL, VITE_QAGENT_API_KEY (desenvolvimento)
npm run dev                    # http://127.0.0.1:5173
npm run build                  # typecheck + build de produção
```

## 4. Decisões e descobertas

1. **CORS:** o Vite serve em `127.0.0.1:5173`, origem diferente de `localhost:5173`. Ambas passaram a estar nas origens por omissão da API (`QAGENT_CORS_ORIGINS`).
2. **Chave LLM:** fica só em memória (estado React), nunca em `localStorage`, e só viaja por cabeçalho (CPS 7.13).
3. **Polling** a cada 1,5 s até estado terminal. SSE/WebSocket ficam para depois.
4. **Idioma:** os rótulos do ecrã estão em inglês, como o testingOn web; os textos gerados pela API (`reason`, `summary`) estão em português. Uniformizar quando se souber o idioma do relatório no testingOn.
5. **Encoding:** os `examples/*.json` foram regravados em UTF-8 (estavam em cp1252 por causa do redirecionamento do `python -m json.tool` no Windows, e o Vite recusava-os).

## 5. Pendentes

- Rótulos exatos do testingOn para falha / não executado (CPS 7.13, ⚠️).
- Ativar os providers no "GenAI Server" e os separadores NL/Gherkin quando a F2/F3 existir.
- O bundle tem ≈ 500 KB minificado (aviso do Vite). É aceitável num protótipo; *code-splitting* só se for portado tal como está.
