param(
    [switch]$SkipSetup
)

$ErrorActionPreference = "Stop"
$AndroidRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

if (-not $SkipSetup) {
    & (Join-Path $PSScriptRoot "setup-cli.ps1")
}

gradle -p $AndroidRoot assembleDebug
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$apk = Join-Path $AndroidRoot "app\build\outputs\apk\debug\app-debug.apk"
if (-not (Test-Path $apk)) {
    throw "APK was not produced: $apk"
}

Write-Host "APK=$apk"
