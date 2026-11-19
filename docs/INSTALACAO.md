# Instalação

Guia para pôr o QAgent a correr numa máquina Windows. No fim tem a API, o appium-mcp e a interface web a funcionar, ligados a um emulador ou dispositivo Android.

## 1. Requisitos

| Requisito | Versão | Notas |
|---|---|---|
| Windows | 10/11 | Os scripts de arranque são PowerShell |
| Python | 3.11 | O projeto exige `>=3.11,<3.12` |
| Node.js | 20 ou mais recente | Para o appium-mcp e a interface web |
| Android SDK | — | Precisa do `adb` no PATH. Caminho por omissão: `C:\Android\Sdk` |
| JDK | — | Caminho por omissão: `C:\Android\JDK` |
| Emulador ou dispositivo Android | — | Com depuração USB ativa; tem de aparecer em `adb devices` |
| Chave de um LLM | — | Azure OpenAI ou Gemini. Só é precisa para texto livre, Gherkin e passos `ai` |
| uv (opcional) | — | Alternativa ao `pip` para o ambiente Python |

Se o SDK ou o JDK estiverem noutros caminhos, altere-os em `scripts\start-appium-mcp.ps1` e `scripts\start-appium-server.ps1`.

## 2. Dependências Python

Há duas formas. Escolha uma.

**Opção A: pip**

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -e . --no-deps
```

A última linha instala o próprio pacote `qagent` (a partir de `src/`) sem voltar a instalar dependências.

Para correr os testes ou os scripts gerados, instale também as dependências de desenvolvimento:

```powershell
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

**Opção B: uv**

```powershell
uv sync
```

O `uv sync` cria o `.venv` e instala tudo, incluindo as dependências de desenvolvimento.

Os dois ficheiros de requisitos têm as versões exatas do `uv.lock`:

| Ficheiro | Conteúdo |
|---|---|
| `requirements.txt` | O que a API precisa para correr |
| `requirements-dev.txt` | Inclui o anterior, mais pytest, httpx e Appium-Python-Client |

Depois de mudar dependências no `pyproject.toml`, regenere-os com os comandos que estão no cabeçalho de cada ficheiro.

## 3. appium-mcp e interface web

```powershell
cd tools\appium-mcp
npm install
cd ..\..\frontend
npm install
cd ..
```

O appium-mcp fica instalado localmente em `tools\appium-mcp`, sem nada global. Já traz o Appium 3 e o driver UiAutomator2.

## 4. Configuração

Copie `.env.example` para `.env` se precisar de mudar alguma omissão. O mínimo é definir as chaves da API:

```powershell
$env:QAGENT_API_KEYS = "<uma-chave-à-sua-escolha>"
```

A interface web lê a URL e a chave da API de `frontend\.env.local`. Use `frontend\.env.example` como base:

```
VITE_QAGENT_API_URL=http://127.0.0.1:8100
VITE_QAGENT_API_KEY=<a mesma chave>
```

Se os testes usarem segredos (`{{secret:nome}}` nos dados de teste), defina-os também como variáveis de ambiente:

```powershell
$env:QAGENT_SECRET_PASSWORD = "<valor>"
```

A lista completa de variáveis está no [README](../README.md), na secção "Configuração".

## 5. Arrancar

Use uma janela de terminal para cada processo, por esta ordem:

1. **Dispositivo.** Arranque o emulador ou ligue o dispositivo e confirme com `adb devices`.
2. **appium-mcp.** Demora 30–60 s a arrancar. Deixe a janela aberta.
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\start-appium-mcp.ps1
   ```
3. **API.**
   ```powershell
   .venv\Scripts\python -m uvicorn qagent.api:app --host 127.0.0.1 --port 8100
   ```
   Use `python -m uvicorn` e não o `uvicorn.exe`: os executáveis da venv podem estar bloqueados pela política da máquina.
4. **Interface web.**
   ```powershell
   cd frontend
   npx vite
   ```
   Fica em http://127.0.0.1:5173.

Mantenha tudo em 127.0.0.1. O appium-mcp não tem autenticação.

## 6. Verificar

Abra http://127.0.0.1:8100/health. Deve responder `"status": "ok"`, com `"ok": true` no `node`, no `adb` e no `appiumMcp`.

O `/health` não confirma que há um dispositivo pronto, por isso veja também `adb devices`.

Para correr os testes automáticos, que não precisam de dispositivo nem de LLM:

```powershell
.venv\Scripts\python -m pytest -q
```

## 7. Correr os scripts gerados (opcional)

Os scripts Python + Appium que o QAgent gera precisam de um servidor Appium normal na porta 4723:

```powershell
.venv\Scripts\python -m pip install -r requirements-dev.txt   # Appium-Python-Client
powershell -ExecutionPolicy Bypass -File scripts\start-appium-server.ps1
python test_<id>.py
```

Não corra o servidor 4723 ao mesmo tempo que uma execução do QAgent no mesmo dispositivo.

## 8. Problemas comuns

| Sintoma | Causa provável |
|---|---|
| `/health` responde 503 com `appiumMcp` em erro | O appium-mcp ainda está a arrancar, ou não está a correr |
| As rotas respondem 503 "QAGENT_API_KEYS não configurado" | Falta definir `QAGENT_API_KEYS` antes de arrancar a API |
| A execução falha logo com erro de ambiente | O dispositivo não está em `adb devices`, ou está bloqueado |
| 400 "exigem um LLM" | Texto livre, Gherkin e passos `ai` precisam dos cabeçalhos `X-Provider` e `X-LLM-*` |
| A interface web não chega à API | `VITE_QAGENT_API_URL`/`VITE_QAGENT_API_KEY` errados, ou origem fora de `QAGENT_CORS_ORIGINS` |
