$ErrorActionPreference = "Stop"

$wslRepoPath = "/home/julian95/projects/Orbika-Quote-Intelligence-Pipeline"

Write-Host "Ejecutando preflight de Orbika..."
wsl.exe -d Ubuntu-26.04 --cd $wslRepoPath -- env PYTHONPATH=. python3 tools/local_console_launcher.py preflight
if ($LASTEXITCODE -ne 0) {
  throw "El preflight reporto errores."
}
