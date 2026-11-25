# Construye dist\BluettiTray.exe (requiere Windows y conexión a Internet la primera vez).
#
#   .\build.ps1              -> ejecutable con ventana (sin consola)
#
# Notas:
#  * Crea un entorno virtual .venv si no existe.
#  * Regenera el icono a partir del código de dibujo (assets\bluetti.ico).

param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Find-Python {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike "*WindowsApps*") { return $cmd.Source }
    throw "No se encontró Python 3.11/3.12. Instálalo desde https://www.python.org/downloads/windows/"
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    $python = Find-Python
    Write-Host "Creando entorno virtual con $python"
    & $python -m venv .venv
}

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt
& $venvPython -m pip install "pyinstaller==6.22.3"

& $venvPython scripts\make_app_icon.py
if ($LASTEXITCODE -ne 0) { throw "No se pudo generar el icono" }

if ($Clean) { Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue }

& $venvPython -m PyInstaller --noconfirm --clean BluettiTray.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falló" }

Write-Host ""
Write-Host "Listo: $root\dist\BluettiTray.exe"
