param(
    [string]$AvdName = "copilot-box-api35",
    [int]$BootTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "setup-cli.ps1") -IncludeEmulator

$emulator = (Get-Command emulator).Source
Start-Process -FilePath $emulator -ArgumentList @("-avd", $AvdName, "-netdelay", "none", "-netspeed", "full")

$deadline = (Get-Date).AddSeconds($BootTimeoutSeconds)
do {
    Start-Sleep -Seconds 5
    $booted = adb shell getprop sys.boot_completed 2>$null
    if ($booted -match "1") {
        Write-Host "Emulator booted: $AvdName"
        exit 0
    }
} while ((Get-Date) -lt $deadline)

throw "Timed out waiting for emulator boot: $AvdName"
