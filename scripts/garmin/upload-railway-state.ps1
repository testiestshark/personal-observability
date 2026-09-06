param(
  [Parameter(Mandatory = $true)]
  [string]$Volume
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$garminDirectory = Join-Path $repositoryRoot ".garmin-sync\garmin"
$appSession = Join-Path $repositoryRoot ".garmin-sync\supabase-session-live.json"

if (-not (Get-Command railway -ErrorAction SilentlyContinue)) {
  throw "Railway CLI is not installed. Install it, run 'railway login' and 'railway link', then retry."
}
if (-not (Test-Path -LiteralPath (Join-Path $garminDirectory "garmin_tokens.json") -PathType Leaf)) {
  throw "Local Garmin tokens are missing. Run 'bun run garmin:status:live' first."
}
if (-not (Test-Path -LiteralPath $appSession -PathType Leaf)) {
  throw "The live app session is missing. Run 'bun run garmin:setup:live' first."
}

Push-Location $repositoryRoot
try {
  & railway volume files --volume $Volume upload $garminDirectory /garmin --overwrite
  if ($LASTEXITCODE -ne 0) { throw "Garmin token upload failed." }

  & railway volume files --volume $Volume upload $appSession /supabase-session-live.json --overwrite
  if ($LASTEXITCODE -ne 0) { throw "App session upload failed." }
}
finally {
  Pop-Location
}

Write-Host "Uploaded both cached sessions to Railway volume '$Volume'."
Write-Host "No passwords were uploaded. The bearer tokens remain sensitive."
