param(
  [ValidateRange(15, 1440)]
  [int]$EveryMinutes = 60
)

$ErrorActionPreference = "Stop"

$taskName = "Personal Observability - Garmin Steps Sync"
$runner = (Resolve-Path (Join-Path $PSScriptRoot "run-sync.ps1")).Path
$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`""

$trigger = New-ScheduledTaskTrigger -Daily -At "00:05"
$trigger.Repetition.Interval = "PT${EveryMinutes}M"
$trigger.Repetition.Duration = "P1D"
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask `
  -TaskName $taskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description "Fetch recent Garmin steps and upsert them into local Personal Observability." `
  -Force | Out-Null

Write-Host "Installed '$taskName' to run every $EveryMinutes minute(s)."
