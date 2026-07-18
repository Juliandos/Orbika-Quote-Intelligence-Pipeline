param(
  [int]$LimitPerPart = 5
)

$ErrorActionPreference = "Stop"

$wslRepoPath = "/home/julian95/projects/Orbika-Quote-Intelligence-Pipeline"
$dbHost = if ($env:ORBIKA_POSTGRES_HOST) { $env:ORBIKA_POSTGRES_HOST } else { "localhost" }
$dbPort = if ($env:ORBIKA_POSTGRES_PORT) { $env:ORBIKA_POSTGRES_PORT } else { "5433" }
$dbName = if ($env:ORBIKA_POSTGRES_DB) { $env:ORBIKA_POSTGRES_DB } else { "orbika_local" }
$dbUser = if ($env:ORBIKA_POSTGRES_USER) { $env:ORBIKA_POSTGRES_USER } else { "orbika" }
$dbPassword = if ($env:ORBIKA_POSTGRES_PASSWORD) { $env:ORBIKA_POSTGRES_PASSWORD } else { "orbika_local_dev_password" }
$databaseUrl = if ($env:DATABASE_URL) {
  $env:DATABASE_URL
} else {
  "postgresql+psycopg://{0}:{1}@{2}:{3}/{4}" -f $dbUser, $dbPassword, $dbHost, $dbPort, $dbName
}

Write-Host "Ejecutando refresco semanal Orbika..."
$command = @(
  "wsl.exe",
  "-d",
  "Ubuntu-26.04",
  "--cd",
  $wslRepoPath,
  "--",
  "env",
  "PYTHONPATH=.",
  "DATABASE_URL=$databaseUrl",
  "python3",
  "tools/local_console_launcher.py",
  "provider-refresh",
  "--limit-per-part",
  "$LimitPerPart"
)
& $command[0] $command[1..($command.Length - 1)]
if ($LASTEXITCODE -ne 0) {
  throw "No se pudo ejecutar el refresco semanal Orbika."
}
Write-Host "Refresco semanal Orbika finalizado."
