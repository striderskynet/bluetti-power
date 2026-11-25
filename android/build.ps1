# Compila el APK de BluettiWidget sin Gradle usando el SDK mínimo de Android.
#
# Requisitos (una sola vez):
#   - JDK 17  -> %LOCALAPPDATA%\BluettiAndroid\jdk17
#   - SDK platform android-34 y build-tools 34.0.0
#     -> %LOCALAPPDATA%\BluettiAndroid\sdk\{platforms\android-34,build-tools\34.0.0}
#   (scripts/setup_toolchain.ps1 de este mismo proyecto los descarga)
#
# Uso:  .\build.ps1
#       .\build.ps1 -SkipTests

param(
    [switch]$SkipTests,
    [string]$Out
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$toolRoot = Join-Path $env:LOCALAPPDATA "BluettiAndroid"
$jdk = Join-Path $toolRoot "jdk17"
$androidJar = Join-Path $toolRoot "sdk\platforms\android-34\android.jar"
$buildTools = Join-Path $toolRoot "sdk\build-tools\34.0.0"
$aapt2 = Join-Path $buildTools "aapt2.exe"
$zipalign = Join-Path $buildTools "zipalign.exe"
$apksigner = Join-Path $buildTools "apksigner.bat"
$javac = Join-Path $jdk "bin\javac.exe"
$java = Join-Path $jdk "bin\java.exe"
$keytool = Join-Path $jdk "bin\keytool.exe"

foreach ($required in @($javac, $java, $keytool, $aapt2, $zipalign, $apksigner, $androidJar)) {
    if (-not (Test-Path $required)) {
        throw "Falta $required. Ejecuta scripts\setup_toolchain.ps1 (ver README de android/)."
    }
}

$env:JAVA_HOME = $jdk
$env:PATH = "$jdk\bin;$env:PATH"

$app = Join-Path $root "app"
$build = Join-Path $root "build"
$out = if ($Out) { $Out } else { Join-Path $root "dist\BluettiWidget.apk" }

Remove-Item -Recurse -Force $build -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force `
    "$build\gen", "$build\classes", "$build\dex", "$build\selftest", (Split-Path $out) | Out-Null

Write-Host "== autoprueba del protocolo ==" -ForegroundColor Cyan
if (-not $SkipTests) {
    & $javac -encoding UTF-8 -d "$build\selftest" `
        "$app\src\main\java\com\striderskynet\bluetti\Hex.java" `
        "$app\src\main\java\com\striderskynet\bluetti\Modbus.java" `
        "$app\src\main\java\com\striderskynet\bluetti\BluettiCrypto.java" `
        "$root\tools\ProtocolSelfTest.java"
    if ($LASTEXITCODE -ne 0) { throw "No compila la autoprueba" }
    & $java -cp "$build\selftest" com.striderskynet.bluetti.ProtocolSelfTest
    if ($LASTEXITCODE -ne 0) { throw "Falló la autoprueba del protocolo" }
}

Write-Host "== recursos ==" -ForegroundColor Cyan
& $aapt2 compile --dir "$app\src\main\res" -o "$build\res.zip"
if ($LASTEXITCODE -ne 0) { throw "aapt2 compile falló" }

& $aapt2 link -o "$build\base.apk" `
    -I $androidJar `
    --manifest "$app\src\main\AndroidManifest.xml" `
    --java "$build\gen" `
    --min-sdk-version 26 `
    --target-sdk-version 34 `
    "$build\res.zip" --auto-add-overlay
if ($LASTEXITCODE -ne 0) { throw "aapt2 link falló" }

Write-Host "== compilando Java ==" -ForegroundColor Cyan
$sources = @(Get-ChildItem "$app\src\main\java" -Recurse -Filter *.java | ForEach-Object { $_.FullName })
$sources += @(Get-ChildItem "$build\gen" -Recurse -Filter R.java | ForEach-Object { $_.FullName })
& $javac -source 8 -target 8 -bootclasspath $androidJar -encoding UTF-8 -Xlint:-options `
    -d "$build\classes" @sources
if ($LASTEXITCODE -ne 0) { throw "javac falló" }

Write-Host "== dex ==" -ForegroundColor Cyan
$classFiles = @(Get-ChildItem "$build\classes" -Recurse -Filter *.class | ForEach-Object { $_.FullName })
& $java -cp "$buildTools\lib\d8.jar" com.android.tools.r8.D8 --release `
    --lib $androidJar --min-api 26 --output "$build\dex" @classFiles
if ($LASTEXITCODE -ne 0) { throw "d8 falló" }

Write-Host "== empaquetando ==" -ForegroundColor Cyan
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open("$build\base.apk", "Update")
try {
    $entry = $zip.CreateEntry("classes.dex", [System.IO.Compression.CompressionLevel]::Optimal)
    $stream = $entry.Open()
    try {
        $dex = [System.IO.File]::ReadAllBytes("$build\dex\classes.dex")
        $stream.Write($dex, 0, $dex.Length)
    } finally {
        $stream.Close()
    }
} finally {
    $zip.Dispose()
}

& $zipalign -f -p 4 "$build\base.apk" "$build\aligned.apk"
if ($LASTEXITCODE -ne 0) { throw "zipalign falló" }

$keystore = Join-Path $root "debug.keystore"
if (-not (Test-Path $keystore)) {
    Write-Host "== creando keystore de depuración ==" -ForegroundColor Cyan
    & $keytool -genkeypair -keystore $keystore -storepass android -keypass android `
        -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 `
        -dname "CN=Android Debug,O=Android,C=US" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "keytool falló" }
}

Write-Host "== firmando ==" -ForegroundColor Cyan
& $apksigner sign --ks $keystore --ks-pass pass:android --key-pass pass:android `
    --out $out "$build\aligned.apk"
if ($LASTEXITCODE -ne 0) { throw "apksigner sign falló" }
& $apksigner verify --print-certs $out | Out-Null
if ($LASTEXITCODE -ne 0) { throw "la firma del APK no es válida" }

$size = (Get-Item $out).Length
Write-Host ""
Write-Host ("APK listo: {0} ({1:N0} KB)" -f $out, ($size / 1KB)) -ForegroundColor Green
