param(
    [string]$ServiceName = "copilot-box",
    [string]$DisplayName = "Copilot Box",
    [string]$Description = "Runs the Copilot Box agent bridge service.",
    [Parameter(Mandatory = $true)]
    [string]$WinSWPath,
    [string]$PythonPath = "python",
    [string]$ConfigPath = "",
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $WinSWPath)) {
    throw "WinSW executable was not found: $WinSWPath"
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $ProjectRoot "config\copilot-box.example.toml"
}

$serviceDir = Join-Path $ProjectRoot ".service"
$logDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $serviceDir, $logDir | Out-Null

$serviceExe = Join-Path $serviceDir "$ServiceName.exe"
$serviceXml = Join-Path $serviceDir "$ServiceName.xml"

Copy-Item -Force $WinSWPath $serviceExe

$escapedProjectRoot = [System.Security.SecurityElement]::Escape($ProjectRoot)
$escapedConfigPath = [System.Security.SecurityElement]::Escape($ConfigPath)
$escapedPythonPath = [System.Security.SecurityElement]::Escape($PythonPath)
$escapedDisplayName = [System.Security.SecurityElement]::Escape($DisplayName)
$escapedDescription = [System.Security.SecurityElement]::Escape($Description)
$escapedLogDir = [System.Security.SecurityElement]::Escape($logDir)

$xml = @"
<service>
  <id>$ServiceName</id>
  <name>$escapedDisplayName</name>
  <description>$escapedDescription</description>
  <executable>$escapedPythonPath</executable>
  <arguments>-m copilot_box service run --config "$escapedConfigPath"</arguments>
  <workingdirectory>$escapedProjectRoot</workingdirectory>
  <env name="PYTHONPATH" value="$escapedProjectRoot\src" />
  <logpath>$escapedLogDir</logpath>
  <log mode="roll-by-time">
    <pattern>yyyyMMdd</pattern>
  </log>
  <onfailure action="restart" delay="10 sec" />
</service>
"@

Set-Content -Path $serviceXml -Value $xml -Encoding UTF8

& $serviceExe install
& $serviceExe start
