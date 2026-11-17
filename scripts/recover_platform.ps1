param(
    [string]$Symbol = "BTCUSDT",
    [string]$Timeframe = "1h",
    [switch]$FillGaps,
    [switch]$RecomputeGold,
    [switch]$RunRetention
)

$ErrorActionPreference = "Stop"
if ($Symbol -notmatch '^[A-Za-z0-9]{3,20}$') {
    throw "Invalid Symbol '$Symbol'. Must be 3..20 alphanumeric characters."
}
if ($Timeframe -notmatch '^(1m|3m|5m|15m|30m|1h|2h|4h|1d)$') {
    throw "Invalid Timeframe '$Timeframe'."
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$env:PYTHONPATH = "."
$env:RECOVER_SYMBOL = $Symbol.ToUpperInvariant()
$env:RECOVER_TIMEFRAME = $Timeframe.ToLowerInvariant()

$py = ".\.venv\Scripts\python.exe"

if ($FillGaps) {
    Write-Output "Running REST backfill & gap healing for $($env:RECOVER_SYMBOL) ($($env:RECOVER_TIMEFRAME))..."
    & $py -c "import asyncio, os; from backend.app.core.database import AsyncSessionLocal; from backend.app.services.sync_service import BinanceSyncService
async def main():
    sym, tf = os.environ['RECOVER_SYMBOL'], os.environ['RECOVER_TIMEFRAME']
    svc = BinanceSyncService()
    async with AsyncSessionLocal() as db:
        r = await svc.sync_incremental(db, sym, tf, 7)
        g = await svc.fill_gaps(db, sym, tf)
        print('Sync:', r, 'GapsFilled:', g)
asyncio.run(main())"
}

if ($RecomputeGold) {
    Write-Output "Recomputing Silver -> Gold Marts & Features for $($env:RECOVER_SYMBOL) ($($env:RECOVER_TIMEFRAME))..."
    & $py -c "import asyncio, os; from backend.app.core.database import AsyncSessionLocal; from backend.app.services.pipeline_service import PipelineService
async def main():
    sym, tf = os.environ['RECOVER_SYMBOL'], os.environ['RECOVER_TIMEFRAME']
    async with AsyncSessionLocal() as db:
        run = await PipelineService.execute_medallion_pipeline(db, sym, tf, trigger_type='RECOVERY', skip_network_ingest=True)
        print('PipelineRun:', run.id, 'Status:', run.status, 'Duration:', run.duration_seconds)
asyncio.run(main())"
}

if ($RunRetention) {
    Write-Output "Enforcing retention policy..."
    & $py -c "from backend.app.services.governance_service import GovernanceService; print(GovernanceService.enforce_retention())"
}

if (-not ($FillGaps -or $RecomputeGold -or $RunRetention)) {
    Write-Output "Usage: .\scripts\recover_platform.ps1 -Symbol BTCUSDT -Timeframe 1h [-FillGaps] [-RecomputeGold] [-RunRetention]"
}
