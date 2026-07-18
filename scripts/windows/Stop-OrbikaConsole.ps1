$ErrorActionPreference = "Stop"

$wslRepoPath = "/home/julian95/projects/Orbika-Quote-Intelligence-Pipeline"

Write-Host "Deteniendo consola Orbika..."
wsl.exe -d Ubuntu-26.04 --cd $wslRepoPath -- env PYTHONPATH=. python3 tools/local_console_launcher.py stop
if ($LASTEXITCODE -ne 0) {
  throw "No se pudo detener la consola Orbika."
}

Write-Host "Consola Orbika detenida."
