param(
    [int]$Port = 4222,
    [int]$HttpPort = 8222,
    [int]$MaxMemMb = 64,
    [int]$MaxFileMb = 128
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$NatsExe = Join-Path $RepoRoot ".bin\nats-server.exe"
$StoreDir = Join-Path $RepoRoot "data\nats"
$ConfPath = Join-Path $RepoRoot "data\nats\nats-local.conf"
$PidFile = Join-Path $RepoRoot "data\nats\nats.pid"

if (-not (Test-Path $NatsExe)) {
    & (Join-Path $PSScriptRoot "install_nats.ps1")
}

New-Item -ItemType Directory -Force -Path $StoreDir | Out-Null

# Check if already listening
$listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Write-Output "NATS JetStream already listening on port $Port (PID $($listening.OwningProcess | Select-Object -First 1))."
    exit 0
}

$storePosix = $StoreDir.Replace("\", "/")
$confContent = @"
port: $Port
http_port: $HttpPort
jetstream {
  store_dir: "$storePosix"
  max_memory_store: ${MaxMemMb}MB
  max_file_store: ${MaxFileMb}MB
}
max_payload: 1MB
"@
[System.IO.File]::WriteAllText($ConfPath, $confContent, [System.Text.UTF8Encoding]::new($false))

$proc = Start-Process -FilePath $NatsExe -ArgumentList @("-js", "-c", $ConfPath, "-P", $PidFile) -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 1
if ($proc.HasExited) {
    throw "nats-server.exe exited unexpectedly with code $($proc.ExitCode)"
}
Write-Output "Started NATS JetStream (PID $($proc.Id)) on nats://127.0.0.1:$Port (monitor http://127.0.0.1:$HttpPort)"
