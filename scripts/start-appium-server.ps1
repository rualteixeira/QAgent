# Servidor Appium 3 (HTTP, porta 4723) para correr os scripts Python gerados pelo QAgent.
# Usa o Appium e o driver uiautomator2 que já vêm com o appium-mcp (tools/appium-mcp) — nada global.
# Uso: powershell -ExecutionPolicy Bypass -File scripts\start-appium-server.ps1
# SEGURANÇA: só 127.0.0.1. Não correr ao mesmo tempo que uma execução do QAgent no mesmo dispositivo.

$root = Split-Path -Parent $PSScriptRoot
$env:APPIUM_HOME = Join-Path $root 'tools\appium-mcp'
$env:ANDROID_HOME = 'C:\Android\Sdk'
$env:ANDROID_SDK_ROOT = 'C:\Android\Sdk'
$env:JAVA_HOME = 'C:\Android\JDK'

& (Join-Path $root 'tools\appium-mcp\node_modules\.bin\appium.cmd') --address 127.0.0.1 --port 4723
