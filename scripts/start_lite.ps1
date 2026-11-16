$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Output "=== Starting Real-Time Financial Intelligence Platform (Profile: LITE) ==="
powershell -ExecutionPolicy Bypass -File .\scripts\start_nats.ps1

$env:PYTHONPATH = "."
$env:PLATFORM_PROFILE = "lite"
.\.venv\Scripts\alembic.exe upgrade head

if (-not (Test-Path "frontend\dist")) {
    Write-Output "Building static React frontend..."
    Push-Location frontend
    npm run build
    Pop-Location
}

Write-Output "Starting FastAPI + Embedded Stream Runtime on http://127.0.0.1:8000 ..."
.\.venv\Scripts\uvicorn.exe backend.app.main:app --host 127.0.0.1 --port 8000

