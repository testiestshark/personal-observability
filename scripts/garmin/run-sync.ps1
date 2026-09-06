$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location -LiteralPath $repoRoot

docker compose --env-file .env.local -f docker-compose.garmin.yml run --rm garmin-sync sync
exit $LASTEXITCODE
