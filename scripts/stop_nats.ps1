$ErrorActionPreference = "SilentlyContinue"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$NatsExe = Join-Path $RepoRoot ".bin\nats-server.exe"
$PidFile = Join-Path $RepoRoot "data\nats\nats.pid"

function Stop-NatsGracefully {
    param([int]$TargetPid)
    $proc = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
    if (-not $proc) { return }

    if (Test-Path $NatsExe) {
        & $NatsExe --signal "quit=$TargetPid" 2>$null | Out-Null
        if ($proc.WaitForExit(5000)) {
            Write-Output "Gracefully stopped NATS JetStream PID $TargetPid"
            return
        }
    }
    Stop-Process -Id $TargetPid -Force
    Write-Output "Force-stopped NATS JetStream PID $TargetPid after graceful timeout"
}

if (Test-Path $PidFile) {
    $pidVal = (Get-Content $PidFile | Select-Object -First 1).Trim()
    if ($pidVal -match '^\d+$') {
        Stop-NatsGracefully -TargetPid ([int]$pidVal)
    }
    Remove-Item $PidFile -Force
} else {
    Get-Process -Name "nats-server" -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-NatsGracefully -TargetPid $_.Id
    }
    Write-Output "Stopped running nats-server processes (if any)."
}
