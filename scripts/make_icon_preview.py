"""Genera la hoja de prueba de iconos en assets/icon-preview.png."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw  # noqa: E402

from bluetti_tray.icon import _font, render_icon  # noqa: E402
from bluetti_tray.status import Status  # noqa: E402

BG_DARK = (24, 30, 42)
BG_LIGHT = (240, 242, 246)

STATES = [
    ("cargando 44%", Status(battery_percent=44, ac_output_power=18, dc_output_power=7, ac_input_power=520, dc_input_power=0, online=True, updated_at=1.0)),
    ("descargando 74%", Status(battery_percent=74, ac_output_power=280, dc_output_power=34, ac_input_power=0, dc_input_power=0, online=True, updated_at=1.0)),
    ("100% reposo", Status(battery_percent=100, ac_output_power=0, dc_output_power=0, ac_input_power=0, dc_input_power=0, online=True, updated_at=1.0)),
    ("20% critico", Status(battery_percent=20, ac_output_power=240, dc_output_power=0, ac_input_power=0, dc_input_power=0, online=True, updated_at=1.0)),
    ("offline", Status(battery_percent=None, online=False, error="sin respuesta")),
    ("1,2 kW", Status(battery_percent=62, ac_output_power=1150, dc_output_power=50, ac_input_power=0, dc_input_power=0, online=True, updated_at=1.0)),
]

ROWS = [
    ("percent", 32, 6, BG_DARK),
    ("percent", 24, 8, BG_DARK),
    ("percent", 24, 8, BG_LIGHT),
    ("power", 32, 6, BG_DARK),
    ("power", 24, 8, BG_DARK),
    ("power", 24, 8, BG_LIGHT),
]


def build(path: Path) -> Path:
    pad = 14
    cell = 24 * 8
    width = pad * 2 + len(STATES) * (cell + pad)
    row_h = cell + 56
    sheet = Image.new("RGB", (width, pad * 2 + len(ROWS) * row_h), BG_DARK)
    draw = ImageDraw.Draw(sheet)
    title_font = _font(15)
    label_font = _font(12)

    y = pad
    for metric, size_px, zoom, bg in ROWS:
        title = f"modo {metric} · {size_px} px reales (ampliado x{zoom}) · {'fondo claro' if bg == BG_LIGHT else 'fondo oscuro'}"
        draw.text((pad, y), title, font=title_font, fill=(210, 210, 210))
        y += 24
        x = pad
        for name, status in STATES:
            icon = render_icon(status, metric=metric, size=size_px, max_output_power=1800)
            big = icon.resize((icon.width * zoom, icon.height * zoom), Image.NEAREST)
            draw.rectangle([x, y, x + big.width, y + big.height], fill=bg)
            sheet.paste(big, (x, y), big)
            draw.text((x, y + big.height + 6), name, font=label_font, fill=(185, 185, 185) if bg == BG_DARK else (60, 60, 60))
            x += big.width + pad
        y += row_h

    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    return path


if __name__ == "__main__":
    print(build(Path("assets/icon-preview.png")))
