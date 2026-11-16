param(
    [string]$Symbol = "BTCUSDT",
    [string]$Timeframe = "1h",
    [switch]$FillGaps,
    [switch]$RecomputeGold,
    [switch]$RunRetention
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$env:PYTHONPATH = "."

$py = ".\.venv\Scripts\python.exe"

if ($FillGaps) {
    Write-Output "Running REST backfill & gap healing for $Symbol ($Timeframe)..."
    & $py -c "import asyncio; from backend.app.core.database import AsyncSessionLocal; from backend.app.services.sync_service import BinanceSyncService;
async def main():
    svc = BinanceSyncService()
    async with AsyncSessionLocal() as db:
        r = await svc.sync_incremental(db, '$Symbol', '$Timeframe', 7)
        g = await svc.fill_gaps(db, '$Symbol', '$Timeframe')
        print('Sync:', r, 'GapsFilled:', g)
asyncio.run(main())"
}

if ($RecomputeGold) {
    Write-Output "Recomputing Silver -> Gold Marts & Features for $Symbol ($Timeframe)..."
    & $py -c "import asyncio; from backend.app.core.database import AsyncSessionLocal; from backend.app.services.pipeline_service import PipelineService;
async def main():
    async with AsyncSessionLocal() as db:
        run = await PipelineService.execute_medallion_pipeline(db, '$Symbol', '$Timeframe', trigger_type='RECOVERY', skip_network_ingest=True)
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

