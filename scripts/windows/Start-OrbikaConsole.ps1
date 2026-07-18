$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\\..")
$wslRepoPath = "/home/julian95/projects/Orbika-Quote-Intelligence-Pipeline"

Write-Host "Iniciando consola Orbika..."
wsl.exe -d Ubuntu-26.04 --cd $wslRepoPath -- env PYTHONPATH=. python3 tools/local_console_launcher.py start
if ($LASTEXITCODE -ne 0) {
  throw "No se pudo iniciar la consola Orbika."
}

Start-Process "http://localhost:3000"
Write-Host "Consola Orbika lista en http://localhost:3000"
