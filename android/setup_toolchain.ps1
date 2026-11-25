# Descarga el toolchain mínimo para compilar el APK sin Android Studio/Gradle:
#   - JDK 17 (Temurin)
#   - Android SDK platform android-34 (android.jar)
#   - Android build-tools 34.0.0 (aapt2, d8, zipalign, apksigner)
#
# Todo queda en %LOCALAPPDATA%\BluettiAndroid. Es idempotente: si ya existe, no
# vuelve a descargar.
#
# Uso:  .\setup_toolchain.ps1

$ErrorActionPreference = "Stop"
$root = Join-Path $env:LOCALAPPDATA "BluettiAndroid"
$downloads = Join-Path $root "dl"
New-Item -ItemType Directory -Force $downloads | Out-Null

function Get-File($url, $path) {
    if (Test-Path $path) {
        Write-Host "  ya existe $(Split-Path $path -Leaf)"
        return
    }
    Write-Host "  descargando $(Split-Path $path -Leaf)…"
    & curl.exe -L --fail -s -o $path $url
    if ($LASTEXITCODE -ne 0) { throw "No se pudo descargar $url" }
}

function Expand-To($zip, $destination) {
    $temp = Join-Path $root ("tmp-" + [System.Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force $temp | Out-Null
    try {
        Expand-Archive -Path $zip -DestinationPath $temp -Force
        $inner = Get-ChildItem $temp -Directory | Select-Object -First 1
        if (-not $inner) { throw "zip vacío: $zip" }
        New-Item -ItemType Directory -Force (Split-Path $destination) | Out-Null
        if (Test-Path $destination) { Remove-Item -Recurse -Force $destination }
        Move-Item $inner.FullName $destination
    } finally {
        Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue
    }
}

$jdkExe = Join-Path $root "jdk17\bin\javac.exe"
if (-not (Test-Path $jdkExe)) {
    $jdkZip = Join-Path $downloads "jdk17.zip"
    Get-File "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse" $jdkZip
    Write-Host "  extrayendo JDK 17…"
    Expand-To $jdkZip (Join-Path $root "jdk17")
}

$androidJar = Join-Path $root "sdk\platforms\android-34\android.jar"
if (-not (Test-Path $androidJar)) {
    $platformZip = Join-Path $downloads "platform-34.zip"
    Get-File "https://dl.google.com/android/repository/platform-34-ext7_r03.zip" $platformZip
    Write-Host "  extrayendo platform android-34…"
    Expand-To $platformZip (Join-Path $root "sdk\platforms\android-34")
}

$aapt2 = Join-Path $root "sdk\build-tools\34.0.0\aapt2.exe"
if (-not (Test-Path $aapt2)) {
    $buildToolsZip = Join-Path $downloads "build-tools-34.zip"
    Get-File "https://dl.google.com/android/repository/build-tools_r34-windows.zip" $buildToolsZip
    Write-Host "  extrayendo build-tools 34.0.0…"
    Expand-To $buildToolsZip (Join-Path $root "sdk\build-tools\34.0.0")
}

Write-Host ""
Write-Host "Toolchain listo en $root" -ForegroundColor Green
Write-Host "  JDK 17:    $jdkExe"
Write-Host "  android.jar: $androidJar"
Write-Host "  build-tools: $aapt2"
Write-Host ""
Write-Host "Ahora ejecuta:  .\build.ps1"
