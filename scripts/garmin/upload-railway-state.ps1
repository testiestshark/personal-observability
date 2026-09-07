param(
  [Parameter(Mandatory = $true)]
  [string]$Volume
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$garminDirectory = Join-Path $repositoryRoot ".garmin-sync\garmin"

if (-not (Get-Command railway -ErrorAction SilentlyContinue)) {
  throw "Railway CLI is not installed. Install it, run 'railway login' and 'railway link', then retry."
}
if (-not (Test-Path -LiteralPath (Join-Path $garminDirectory "garmin_tokens.json") -PathType Leaf)) {
  throw "Local Garmin tokens are missing. Run 'bun run garmin:status:live' first."
}
Push-Location $repositoryRoot
try {
  & railway volume files --volume $Volume upload $garminDirectory /garmin --overwrite
  if ($LASTEXITCODE -ne 0) { throw "Garmin token upload failed." }

}
finally {
  Pop-Location
}

Write-Host "Uploaded the cached Garmin session to Railway volume '$Volume'."
Write-Host "The app session is created afresh from private Railway variables on every run."
