"""Dibujo del icono de la bandeja (PIL) a partir del estado del equipo."""

from __future__ import annotations

import functools
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .status import Status, band, fmt_power_compact

#: Factor de supersampling para bordes y texto suaves.
SS = 4

COLORS = {
    "good": (74, 222, 128),
    "warn": (250, 204, 21),
    "bad": (248, 113, 113),
    "unknown": (148, 163, 184),
}
BADGE_OFFLINE = (30, 41, 59)
BADGE_BG = (15, 23, 42)
BADGE_RIMMED = (51, 65, 85)
RING_BG = (71, 85, 105)
TEXT = (248, 250, 252)
TEXT_DIM = (148, 163, 184)
CHARGING = (56, 189, 248)
BOLT = (250, 204, 21)


@functools.lru_cache(maxsize=64)
def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    names = (
        ["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf", "arial.ttf"]
        if bold
        else ["segoeui.ttf", "arial.ttf"]
    )
    for name in names:
        path = windir / "Fonts" / name
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: float, start: int, minimum: int = 8):
    size = max(minimum, start)
    while size > minimum:
        font = _font(size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 1
    return _font(minimum)


def _draw_text(draw: ImageDraw.ImageDraw, xy, text: str, font, color) -> None:
    shadow = (0, 0, 0, 160)
    draw.text((xy[0] + max(1, font.size * 0.05), xy[1] + max(1, font.size * 0.05)), text, font=font, fill=shadow, anchor="mm")
    draw.text(xy, text, font=font, fill=color, anchor="mm")


def _bolt(draw: ImageDraw.ImageDraw, s: float, color) -> None:
    """Rayito pequeño en la esquina inferior derecha del icono."""
    cx, cy = s * 0.795, s * 0.775
    w, h = s * 0.075, s * 0.125
    points = [
        (cx - w * 0.55, cy - h * 0.5),
        (cx + w * 0.55, cy - h * 0.5),
        (cx - w * 0.05, cy + h * 0.02),
        (cx + w * 0.10, cy + h * 0.02),
        (cx - w * 0.45, cy + h * 0.55),
    ]
    draw.polygon(points, fill=color + (255,))


def _ring(draw, s: int, frac: float, color) -> None:
    pad = s * 0.02
    width = max(2, int(s * 0.105))
    radius = s / 2 - pad - width / 2 - s * 0.015
    box = [s / 2 - radius, s / 2 - radius, s / 2 + radius, s / 2 + radius]
    draw.arc(box, 0, 360, fill=RING_BG + (255,), width=width)
    if frac > 0:
        draw.arc(box, -90, -90 + frac * 360, fill=color + (255,), width=width)


def _texts(status: Status, metric: str, max_width: float, s: int) -> tuple[str, str, int, int]:
    """Devuelve (línea1, línea2, tamaño1, tamaño2) según el modo del icono."""
    percent = status.battery_percent
    watts = status.total_output_power
    if metric == "power":
        return fmt_power_compact(watts) + ("W" if watts is not None else ""), "", int(s * 0.34), 0
    if metric == "both":
        line1 = f"{percent}%" if percent is not None else "—"
        line2 = (fmt_power_compact(watts) + "W") if watts is not None else ""
        return line1, line2, int(s * 0.24), int(s * 0.20)
    line = f"{percent}%" if percent is not None else "—"
    return line, "", int(s * 0.40), 0


def render_icon(
    status: Status,
    metric: str = "percent",
    size: int = 64,
    max_output_power: int = 1800,
) -> Image.Image:
    """Genera el icono de bandeja para el estado dado."""
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    online = status.online
    charging = online and status.mode in ("charging", "passthrough")
    badge_bg = BADGE_BG if online else BADGE_OFFLINE

    pad = s * 0.015
    draw.ellipse([pad, pad, s - pad, s - pad], fill=badge_bg + (255,))

    if metric == "power":
        fraction = min(1.0, (status.total_output_power or 0) / max(1, max_output_power))
        if fraction < 0.5:
            ring_color = COLORS["good"]
        elif fraction < 0.85:
            ring_color = COLORS["warn"]
        else:
            ring_color = COLORS["bad"]
    else:
        fraction = (status.battery_percent or 0) / 100.0 if online else 0.0
        ring_color = COLORS[band(status.battery_percent)] if online else COLORS["unknown"]

    if charging:
        ring_color = CHARGING

    _ring(draw, s, min(1.0, max(0.0, fraction)), ring_color)

    line1, line2, size1, size2 = _texts(status, metric, s * 0.8, s)
    text_width = s * 0.66
    if line2:
        font1 = _fit_font(draw, line1, text_width * 1.05, size1)
        font2 = _fit_font(draw, line2, text_width, size2)
        _draw_text(draw, (s / 2, s / 2 - s * 0.115), line1, font1, TEXT)
        _draw_text(draw, (s / 2, s / 2 + s * 0.150), line2, font2, TEXT_DIM if online else TEXT_DIM)
    else:
        color = TEXT if online else TEXT_DIM
        font = _fit_font(draw, line1, text_width, size1)
        _draw_text(draw, (s / 2, s / 2), line1, font, color)

    if charging and metric != "both":
        _bolt(draw, s, BOLT)

    return img.resize((size, size), Image.LANCZOS)


def make_app_icon(size: int = 256) -> Image.Image:
    """Icono de la aplicación (.ico del ejecutable)."""
    s = size * 2
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = s * 0.04
    radius = s * 0.18
    draw.rounded_rectangle([pad, pad, s - pad, s - pad], radius=radius, fill=BADGE_BG + (255,))
    ring_box = [s * 0.20, s * 0.20, s * 0.80, s * 0.80]
    draw.arc(ring_box, 0, 360, fill=BADGE_RIMMED + (255,), width=int(s * 0.055))
    draw.arc(ring_box, -90, 170, fill=COLORS["good"] + (255,), width=int(s * 0.055))

    # Rayo central
    cx, cy = s * 0.52, s * 0.50
    w, h = s * 0.13, s * 0.34
    points = [
        (cx + w * 0.10, cy - h * 0.55),
        (cx - w * 0.75, cy + h * 0.10),
        (cx - w * 0.10, cy + h * 0.10),
        (cx - w * 0.35, cy + h * 0.60),
        (cx + w * 0.75, cy - h * 0.12),
        (cx + w * 0.05, cy - h * 0.12),
    ]
    draw.polygon(points, fill=BOLT + (255,))
    return img.resize((size, size), Image.LANCZOS)


def write_ico(path: Path, sizes: tuple[int, ...] = (16, 20, 24, 32, 40, 48, 64, 128, 256)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    base = make_app_icon(256)
    base.save(path, format="ICO", sizes=[(s, s) for s in sizes])
    return path


def preview_sheet(path: Path) -> Path:
    """Hoja de prueba con distintos estados y tamaños (para revisar legibilidad)."""
    from .demo import demo_status
    from .status import Status

    now = 0.0
    samples = [
        ("cargando", demo_status(5)),
        ("descargando", demo_status(70)),
        ("reposo", Status(battery_percent=87, ac_output_power=0, dc_output_power=0, ac_input_power=0, dc_input_power=0, online=True, updated_at=now)),
        ("20 %", Status(battery_percent=20, ac_output_power=240, dc_output_power=0, ac_input_power=0, dc_input_power=0, online=True, updated_at=now)),
        ("offline", Status(battery_percent=None, online=False, error="sin respuesta")),
    ]
    zoom = 4
    tile = 64
    pad = 14
    bg_dark = (24, 30, 42)
    bg_light = (238, 240, 244)

    width = pad + len(samples) * (tile * zoom + pad)
    sheet = Image.new("RGB", (width * 2, 2 * (tile * zoom + pad) + pad * 2 + 24), bg_dark)
    draw = ImageDraw.Draw(sheet)
    label_font = _font(14)

    def place(bg, top, title):
        draw.text((pad, top), title, font=label_font, fill=(200, 200, 200) if bg == bg_dark else (60, 60, 60), anchor="lt")
        x = pad
        for name, status in samples:
            icon = render_icon(status, metric="both", size=tile, max_output_power=1800)
            big = icon.resize((tile * zoom, tile * zoom), Image.NEAREST)
            y = top + 22
            draw.rectangle([x, y, x + tile * zoom, y + tile * zoom], fill=bg)
            sheet.paste(big, (x, y), big)
            x += tile * zoom + pad
        return top + tile * zoom + pad + 8

    y = place(bg_dark, pad, "fondo oscuro (tema Windows oscuro)")
    draw.text((pad, y), "tamaño real: 64 px a la izquierda, luego 32, 24 y 16 (ampliados x4)", font=label_font, fill=(180, 180, 180))
    y += 26
    # Tamaños reales de bandeja, ampliados
    x = pad
    for size_px in (64, 32, 24, 16):
        for name, status in samples[:3]:
            icon = render_icon(status, metric="both", size=size_px)
            big = icon.resize((size_px * 6, size_px * 6), Image.NEAREST)
            sheet.paste(big, (x, y), big)
            x += size_px * 6 + pad
    y += 64 * 6 + pad
    y = place(bg_light, y, "fondo claro (tema Windows claro)")

    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    return path
