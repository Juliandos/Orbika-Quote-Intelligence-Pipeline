param(
  [string]$TaskName = "OrbikaConsole-WeeklyMaintenance",
  [ValidateSet("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")]
  [string]$DayOfWeek = "Sunday",
  [string]$At = "08:00",
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$maintenanceScript = Join-Path $PSScriptRoot "Maintenance-OrbikaConsole.ps1"
if (-not (Test-Path $maintenanceScript)) {
  throw "No se encontro el wrapper de mantenimiento: $maintenanceScript"
}

try {
  $runAt = (Get-Date).Date.Add([TimeSpan]::Parse($At))
} catch {
  throw "Hora invalida para el Programador de tareas: '$At'. Usa formato HH:mm, por ejemplo 08:00."
}

$quotedMaintenanceScript = '"{0}"' -f $maintenanceScript
$taskArguments = '-NoProfile -ExecutionPolicy Bypass -File {0} -Apply' -f $quotedMaintenanceScript
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $taskArguments
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DayOfWeek -At $runAt
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew

if ($Force) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Orbika weekly maintenance and retention cleanup.' | Out-Null

[pscustomobject]@{
  task_name = $TaskName
  day_of_week = $DayOfWeek
  run_at = $runAt.ToString('HH:mm')
  apply = $true
  wrapper = $maintenanceScript
  status = 'registered'
}