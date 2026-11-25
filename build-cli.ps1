# Construye dist\BluettiTrayCLI.exe (versión de consola para diagnóstico).
# Requiere haber ejecutado antes .\build.ps1 (o al menos tener .venv con dependencias).

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Falta .venv. Ejecuta primero .\build.ps1"
}

& $venvPython scripts\make_app_icon.py
& $venvPython -m PyInstaller --noconfirm --clean BluettiTrayCLI.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falló" }

Write-Host ""
Write-Host "Listo: $root\dist\BluettiTrayCLI.exe"
Write-Host "Ejemplos:  .\dist\BluettiTrayCLI.exe scan"
Write-Host "           .\dist\BluettiTrayCLI.exe read --raw"
Write-Host "           .\dist\BluettiTrayCLI.exe detect --address AA:BB:CC:DD:EE:FF"
