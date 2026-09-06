$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $repoRoot

docker compose `
  --env-file .env.production `
  -f docker-compose.garmin.yml `
  -f docker-compose.garmin.live.yml `
  run --rm garmin-sync sync
exit $LASTEXITCODE
