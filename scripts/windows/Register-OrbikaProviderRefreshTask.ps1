param(
  [string]$TaskName = "OrbikaConsole-WeeklyProviderRefresh",
  [ValidateSet("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")]
  [string]$DayOfWeek = "Sunday",
  [string]$At = "09:00",
  [int]$LimitPerPart = 5,
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$refreshScript = Join-Path $PSScriptRoot "ProviderRefresh-OrbikaConsole.ps1"
if (-not (Test-Path $refreshScript)) {
  throw "No se encontro el wrapper de refresco semanal: $refreshScript"
}

try {
  $runAt = (Get-Date).Date.Add([TimeSpan]::Parse($At))
} catch {
  throw "Hora invalida para el Programador de tareas: '$At'. Usa formato HH:mm, por ejemplo 09:00."
}

$quotedRefreshScript = '"{0}"' -f $refreshScript
$taskArguments = '-NoProfile -ExecutionPolicy Bypass -File {0} -LimitPerPart {1}' -f $quotedRefreshScript, $LimitPerPart
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $taskArguments
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DayOfWeek -At $runAt
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew

if ($Force) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Orbika weekly provider refresh and PostgreSQL sync.' | Out-Null

[pscustomobject]@{
  task_name = $TaskName
  day_of_week = $DayOfWeek
  run_at = $runAt.ToString('HH:mm')
  limit_per_part = $LimitPerPart
  wrapper = $refreshScript
  status = 'registered'
}
