"""Inicio automático con Windows mediante un acceso directo en la carpeta Startup."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from .paths import app_data_dir, autostart_shortcut, is_frozen, launch_command

_LOGGER = logging.getLogger(__name__)
_CREATE_NO_WINDOW = 0x08000000


def is_enabled() -> bool:
    return autostart_shortcut().exists()


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def set_enabled(enabled: bool) -> None:
    """Crea o elimina el acceso directo de inicio automático."""
    shortcut = autostart_shortcut()
    if not enabled:
        shortcut.unlink(missing_ok=True)
        return

    shortcut.parent.mkdir(parents=True, exist_ok=True)
    target, arguments, workdir = launch_command()
    script = (
        "$ws = New-Object -ComObject WScript.Shell\n"
        f"$sc = $ws.CreateShortcut({_ps_quote(str(shortcut))})\n"
        f"$sc.TargetPath = {_ps_quote(target)}\n"
        f"$sc.Arguments = {_ps_quote(arguments)}\n"
        f"$sc.WorkingDirectory = {_ps_quote(workdir)}\n"
        f"$sc.IconLocation = {_ps_quote(target)}\n"
        "$sc.Save()\n"
    )
    script_path = Path(tempfile.mkstemp(prefix="bluetti-autostart-", suffix=".ps1", dir=app_data_dir())[1])
    try:
        script_path.write_text(script, encoding="utf-8-sig")
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
            ],
            check=True,
            timeout=30,
            creationflags=_CREATE_NO_WINDOW,
            capture_output=True,
        )
        _LOGGER.info("Inicio automático %s (%s)", "activado" if enabled else "desactivado", shortcut)
    finally:
        script_path.unlink(missing_ok=True)


def open_log_folder() -> None:
    os.startfile(str(app_data_dir()))  # noqa: S606 - carpeta propia
