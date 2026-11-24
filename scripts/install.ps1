# Copy custom_components/qixu_mcp to Home Assistant over the SSH add-on.
#   .\scripts\install.ps1                      # key auth
#   .\scripts\install.ps1 -HaHost 192.168.1.10 -Port 22222
# Restart Home Assistant afterwards; reloading the integration does not re-import Python.

param(
  [string]$HaHost = "homeassistant.local",
  [int]$Port = 22222,
  [string]$User = "root"
)

$ErrorActionPreference = "Stop"
$src = Join-Path $PSScriptRoot "..\custom_components\qixu_mcp" | Resolve-Path
$remoteDst = "/config/custom_components/qixu_mcp"

Get-ChildItem $src -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force

scp -P $Port -o StrictHostKeyChecking=accept-new -r "$src" "${User}@${HaHost}:/tmp/qixu_mcp"
ssh -p $Port -o StrictHostKeyChecking=accept-new "${User}@${HaHost}" `
  "mkdir -p /config/custom_components && rm -rf $remoteDst && mv /tmp/qixu_mcp $remoteDst && ls $remoteDst"

Write-Host "Installed to $remoteDst. Restart Home Assistant, then add the integration 栖序 MCP."
