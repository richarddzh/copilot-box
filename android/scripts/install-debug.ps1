param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$AndroidRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot "build-debug.ps1")
} else {
    & (Join-Path $PSScriptRoot "setup-cli.ps1")
}

$apk = Join-Path $AndroidRoot "app\build\outputs\apk\debug\app-debug.apk"
adb install -r $apk
