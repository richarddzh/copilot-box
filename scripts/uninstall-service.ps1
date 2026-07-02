param(
    [string]$ServiceName = "copilot-box",
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$serviceExe = Join-Path $ProjectRoot ".service\$ServiceName.exe"

if (-not (Test-Path $serviceExe)) {
    throw "Service executable was not found: $serviceExe"
}

& $serviceExe stop
& $serviceExe uninstall
