param(
  [ValidateRange(15, 1440)]
  [int]$EveryMinutes = 60
)

$ErrorActionPreference = "Stop"

$taskName = "Personal Observability - Garmin Steps Live Sync"
$runner = (Resolve-Path (Join-Path $PSScriptRoot "run-sync-live.ps1")).Path
$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`""

$repetition = New-ScheduledTaskTrigger `
  -Once `
  -At (Get-Date) `
  -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
  -RepetitionDuration (New-TimeSpan -Days 1)
$trigger = New-ScheduledTaskTrigger -Daily -At "00:05"
$trigger.Repetition = $repetition.Repetition
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask `
  -TaskName $taskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description "Fetch recent Garmin steps and upsert them into hosted Personal Observability." `
  -Force | Out-Null

Write-Host "Installed '$taskName' to run every $EveryMinutes minute(s)."
