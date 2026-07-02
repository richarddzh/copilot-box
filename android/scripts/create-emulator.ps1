param(
    [string]$AvdName = "copilot-box-api35",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "setup-cli.ps1") -IncludeEmulator

if ($Force) {
    avdmanager delete avd -n $AvdName | Out-Host
}

$existing = avdmanager list avd | Select-String -Pattern "Name: $AvdName" -Quiet
if (-not $existing) {
    "no" | avdmanager create avd `
        -n $AvdName `
        -k "system-images;android-35;google_apis;x86_64" `
        -d "pixel_6"
}

Write-Host "AVD=$AvdName"
