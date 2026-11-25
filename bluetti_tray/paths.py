"""Rutas de archivos y utilidades comunes del proyecto."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "BluettiTray"


def is_frozen() -> bool:
    """True si estamos corriendo dentro de un ejecutable de PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def app_data_dir() -> Path:
    """Carpeta de datos de usuario: %LOCALAPPDATA%\\BluettiTray."""
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    directory = root / APP_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def config_path() -> Path:
    override = os.environ.get("BLUETTI_CONFIG")
    if override:
        return Path(override)
    return app_data_dir() / "config.json"


def log_path() -> Path:
    return app_data_dir() / "bluetti-tray.log"


def autostart_dir() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def autostart_shortcut() -> Path:
    return autostart_dir() / f"{APP_NAME}.lnk"


def resource_path(relative: str) -> Path:
    """Ruta a un recurso empaquetado (assets/...) tanto en fuente como en el .exe."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    return base / relative


def launch_command() -> tuple[str, str, str]:
    """Devuelve (target, arguments, working_dir) para iniciar la app con Windows."""
    if is_frozen():
        exe = Path(sys.executable).resolve()
        return str(exe), "", str(exe.parent)

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    project = Path(__file__).resolve().parent.parent
    return str(interpreter), str(project / "main.py"), str(project)
