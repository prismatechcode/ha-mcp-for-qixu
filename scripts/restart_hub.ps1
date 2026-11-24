# Restart local Qixu hub on :8791 (keeps the token HA already uses).
param(
  [string]$TokenFile = (Join-Path $PSScriptRoot "..\dist\hub.token.txt"),
  [int]$Port = 8791
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$token = (Get-Content -Raw $TokenFile).Trim()
$py = Join-Path $root ".venv-test\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

netstat -ano | Select-String ":$Port\s+.LISTENING" | ForEach-Object {
  $parts = ($_ -split '\s+') | Where-Object { $_ }
  $procId = $parts[-1]
  if ($procId -match '^\d+$') {
    taskkill /PID $procId /F 2>$null | Out-Null
  }
}

$out = Join-Path $root "dist\hub.out.log"
$err = Join-Path $root "dist\hub.err.log"
Start-Process -FilePath $py -ArgumentList @(
  (Join-Path $root "hub\qixu_hub.py"),
  "--host", "0.0.0.0",
  "--port", "$Port",
  "--token", $token
) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err

Start-Sleep -Seconds 1
Write-Host "hub restarted on port $Port"
Write-Host "voice: POST http://127.0.0.1:$Port/v1/voice"
Write-Host "mcp:   ws://<LAN-IP>:$Port/mcp"
