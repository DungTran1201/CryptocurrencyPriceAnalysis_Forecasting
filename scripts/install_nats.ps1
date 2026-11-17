$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BinDir = Join-Path $RepoRoot ".bin"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$TargetExe = Join-Path $BinDir "nats-server.exe"

if (Test-Path $TargetExe) {
    Write-Output "nats-server.exe already present at $TargetExe"
    & $TargetExe --version
    exit 0
}

$release = Invoke-RestMethod -Uri "https://api.github.com/repos/nats-io/nats-server/releases/latest" -Headers @{ "User-Agent" = "CryptoPlatformInstaller" }
$asset = $release.assets | Where-Object { $_.name -like "*windows-amd64.zip" } | Select-Object -First 1
if (-not $asset) {
    throw "Could not find windows-amd64.zip asset in latest nats-server release."
}

$zipPath = Join-Path $BinDir $asset.name
$extractDir = Join-Path $BinDir "extract_tmp"
Write-Output "Downloading $($asset.browser_download_url)..."
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath

$actualHash = (Get-FileHash -Path $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$shaAsset = $release.assets | Where-Object { $_.name -match "(?i)sha256|checksum" } | Select-Object -First 1
if ($shaAsset) {
    $shaPath = Join-Path $BinDir $shaAsset.name
    Invoke-WebRequest -Uri $shaAsset.browser_download_url -OutFile $shaPath
    $shaLine = Get-Content $shaPath | Where-Object { $_ -match [regex]::Escape($asset.name) } | Select-Object -First 1
    Remove-Item -Force $shaPath -ErrorAction SilentlyContinue
    if ($shaLine -and $shaLine -match '([a-fA-F0-9]{64})') {
        $expectedHash = $Matches[1].ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            Remove-Item -Force $zipPath -ErrorAction SilentlyContinue
            throw "SHA256 verification FAILED for $($asset.name): expected $expectedHash, got $actualHash"
        }
        Write-Output "Verified SHA256 checksum ($actualHash) for $($asset.name)."
    }
} else {
    Write-Warning "Release $($release.tag_name) has no SHA256 manifest asset; computed SHA256=$actualHash"
}

if (Test-Path $extractDir) { Remove-Item -Recurse -Force $extractDir }
Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

$exe = Get-ChildItem -Path $extractDir -Recurse -Filter "nats-server.exe" | Select-Object -First 1
if (-not $exe) {
    throw "nats-server.exe not found inside downloaded zip."
}
Copy-Item -Path $exe.FullName -Destination $TargetExe -Force
Remove-Item -Recurse -Force $extractDir
Remove-Item -Force $zipPath

Write-Output "Installed $TargetExe (SHA256=$actualHash)"
& $TargetExe --version
