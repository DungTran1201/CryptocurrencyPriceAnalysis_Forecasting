$ErrorActionPreference = "SilentlyContinue"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $RepoRoot "data\nats\nats.pid"

if (Test-Path $PidFile) {
    $pidVal = (Get-Content $PidFile | Select-Object -First 1).Trim()
    if ($pidVal -match '^\d+$') {
        Stop-Process -Id ([int]$pidVal) -Force
        Write-Output "Stopped NATS JetStream PID $pidVal"
    }
    Remove-Item $PidFile -Force
} else {
    Get-Process -Name "nats-server" -ErrorAction SilentlyContinue | Stop-Process -Force
    Write-Output "Stopped running nats-server processes (if any)."
}

