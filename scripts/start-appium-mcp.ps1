# Arranca o appium-mcp 1.99.3 como servidor HTTP local (apenas 127.0.0.1:8080).
# Uso: powershell -ExecutionPolicy Bypass -File scripts\start-appium-mcp.ps1
# O arranque demora ~30-60 s (I/O de node_modules + antivírus). Deixar a janela aberta.
# SEGURANÇA: o appium-mcp não tem autenticação. Não alterar FASTMCP_HOST para 0.0.0.0.

$root = Split-Path -Parent $PSScriptRoot

$env:FASTMCP_HOST = '127.0.0.1'
$env:ANDROID_HOME = 'C:\Android\Sdk'
$env:ANDROID_SDK_ROOT = 'C:\Android\Sdk'
$env:JAVA_HOME = 'C:\Android\JDK'
$env:CAPABILITIES_CONFIG = Join-Path $root 'config\capabilities.json'
# Pastas temporárias do servidor (o QAgent copia a evidência para runs\<execução>\).
$env:SCREENSHOTS_DIR = Join-Path $root 'runs\_mcp-server\screenshots'
$env:PAGE_SOURCES_DIR = Join-Path $root 'runs\_mcp-server\pagesources'
$env:NO_UI = 'true'
$env:APPIUM_MCP_ON_CLIENT_DISCONNECT = 'delete_all'
$env:APPIUM_MCP_EVIDENCE = 'true'
$env:ALLOW_REMOTE_APP_URLS = 'false'
$env:AI_VISION_ENABLED = 'false'

node (Join-Path $root 'tools\appium-mcp\node_modules\appium-mcp\dist\index.js') --httpStream --port=8080
