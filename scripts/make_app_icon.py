"""Genera el icono de la aplicación (assets/bluetti.ico)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bluetti_tray.icon import write_ico  # noqa: E402


def main() -> None:
    target = Path(__file__).resolve().parent.parent / "assets" / "bluetti.ico"
    write_ico(target)
    print(f"Generado {target}")


if __name__ == "__main__":
    main()
