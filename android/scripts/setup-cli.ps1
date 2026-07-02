param(
    [string]$ToolsDir = "",
    [string]$AndroidSdkRoot = "",
    [string]$GradleVersion = "8.10.2",
    [string]$AndroidPlatform = "android-35",
    [string]$BuildToolsVersion = "35.0.0",
    [switch]$IncludeEmulator
)

$ErrorActionPreference = "Stop"

$AndroidRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$RepoRoot = Resolve-Path (Join-Path $AndroidRoot "..")

if ([string]::IsNullOrWhiteSpace($ToolsDir)) {
    $ToolsDir = Join-Path $RepoRoot ".tools\android-cli"
}
if ([string]::IsNullOrWhiteSpace($AndroidSdkRoot)) {
    $AndroidSdkRoot = Join-Path $ToolsDir "android-sdk"
}

$ToolsDir = [System.IO.Path]::GetFullPath($ToolsDir)
$AndroidSdkRoot = [System.IO.Path]::GetFullPath($AndroidSdkRoot)
New-Item -ItemType Directory -Force -Path $ToolsDir, $AndroidSdkRoot | Out-Null

function Expand-ZipIfMissing {
    param(
        [string]$Url,
        [string]$ZipPath,
        [string]$Destination,
        [string]$Probe
    )

    if (Test-Path $Probe) {
        return
    }

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    if (-not (Test-Path $ZipPath)) {
        Invoke-WebRequest -Uri $Url -OutFile $ZipPath
    }
    Expand-Archive -Path $ZipPath -DestinationPath $Destination -Force
}

$jdkDir = Join-Path $ToolsDir "jdk-17"
$jdkZip = Join-Path $ToolsDir "jdk-17.zip"
$jdkProbe = Join-Path $jdkDir "bin\java.exe"
if (-not (Test-Path $jdkProbe)) {
    Expand-ZipIfMissing `
        -Url "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse?project=jdk" `
        -ZipPath $jdkZip `
        -Destination $jdkDir `
        -Probe $jdkProbe
    $nestedJava = Get-ChildItem -Path $jdkDir -Recurse -Filter java.exe |
        Where-Object { $_.FullName -like "*\bin\java.exe" } |
        Select-Object -First 1
    if (-not $nestedJava) {
        throw "Downloaded JDK did not contain java.exe"
    }
    $actualJdkRoot = Split-Path -Parent (Split-Path -Parent $nestedJava.FullName)
    if ($actualJdkRoot -ne $jdkDir) {
        Get-ChildItem -Path $actualJdkRoot -Force | Move-Item -Destination $jdkDir -Force
        Remove-Item -Recurse -Force $actualJdkRoot
    }
}

$gradleRoot = Join-Path $ToolsDir "gradle-$GradleVersion"
$gradleZip = Join-Path $ToolsDir "gradle-$GradleVersion-bin.zip"
$gradleProbe = Join-Path $gradleRoot "bin\gradle.bat"
Expand-ZipIfMissing `
    -Url "https://services.gradle.org/distributions/gradle-$GradleVersion-bin.zip" `
    -ZipPath $gradleZip `
    -Destination $ToolsDir `
    -Probe $gradleProbe

$cmdlineLatest = Join-Path $AndroidSdkRoot "cmdline-tools\latest"
$sdkManager = Join-Path $cmdlineLatest "bin\sdkmanager.bat"
if (-not (Test-Path $sdkManager)) {
    $cmdlineZip = Join-Path $ToolsDir "commandlinetools-win.zip"
    $cmdlineTemp = Join-Path $ToolsDir "cmdline-tools-temp"
    Remove-Item -Recurse -Force $cmdlineTemp -ErrorAction SilentlyContinue
    Expand-ZipIfMissing `
        -Url "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip" `
        -ZipPath $cmdlineZip `
        -Destination $cmdlineTemp `
        -Probe (Join-Path $cmdlineTemp "cmdline-tools\bin\sdkmanager.bat")
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $cmdlineLatest) | Out-Null
    Move-Item -Force (Join-Path $cmdlineTemp "cmdline-tools") $cmdlineLatest
    Remove-Item -Recurse -Force $cmdlineTemp
}

$env:JAVA_HOME = $jdkDir
$env:ANDROID_HOME = $AndroidSdkRoot
$env:ANDROID_SDK_ROOT = $AndroidSdkRoot
$env:Path = "$jdkDir\bin;$gradleRoot\bin;$cmdlineLatest\bin;$AndroidSdkRoot\platform-tools;$AndroidSdkRoot\emulator;$env:Path"

$packages = @(
    "platform-tools",
    "platforms;$AndroidPlatform",
    "build-tools;$BuildToolsVersion"
)

if ($IncludeEmulator) {
    $packages += @(
        "emulator",
        "system-images;$AndroidPlatform;google_apis;x86_64"
    )
}

$licenseInput = Join-Path $ToolsDir "accept-android-licenses.txt"
1..100 | ForEach-Object { "y" } | Set-Content -Path $licenseInput -Encoding ASCII
& $env:ComSpec /c "`"$sdkManager`" --licenses < `"$licenseInput`""
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& $sdkManager @packages
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$localProperties = Join-Path $AndroidRoot "local.properties"
"sdk.dir=$($AndroidSdkRoot.Replace('\', '\\'))" | Set-Content -Path $localProperties -Encoding ASCII

Write-Host "JAVA_HOME=$env:JAVA_HOME"
Write-Host "ANDROID_HOME=$env:ANDROID_HOME"
Write-Host "Gradle=$gradleRoot"
Write-Host "Android local.properties=$localProperties"
