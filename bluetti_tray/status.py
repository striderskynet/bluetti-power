"""Estado de la batería y utilidades de formato compartidas por bandeja, panel y CLI."""

from __future__ import annotations

import time
from dataclasses import dataclass

# Potencia a partir de la cual consideramos que hay consumo / entrada.
OUTPUT_ON_THRESHOLD = 5  # W
INPUT_ON_THRESHOLD = 5  # W

MODE_IDLE = "idle"
MODE_CHARGING = "charging"
MODE_DISCHARGING = "discharging"
MODE_PASSTHROUGH = "passthrough"
MODE_UNKNOWN = "unknown"

MODE_LABELS = {
    MODE_CHARGING: "Cargando",
    MODE_DISCHARGING: "Descargando",
    MODE_PASSTHROUGH: "Entrada y salida activas",
    MODE_IDLE: "En reposo",
    MODE_UNKNOWN: "Sin datos",
}

MODE_SHORT_LABELS = {
    MODE_CHARGING: "cargando",
    MODE_DISCHARGING: "descargando",
    MODE_PASSTHROUGH: "pasante",
    MODE_IDLE: "reposo",
    MODE_UNKNOWN: "sin datos",
}

DASH = "—"


@dataclass
class Status:
    """Última lectura conocida del equipo."""

    battery_percent: int | None = None
    ac_output_power: int | None = None
    dc_output_power: int | None = None
    ac_input_power: int | None = None
    dc_input_power: int | None = None
    device_type: str = ""
    device_sn: str = ""
    device_name: str = ""
    address: str = ""
    encrypted: bool = False
    online: bool = False
    source: str = "ble"
    error: str | None = None
    updated_at: float = 0.0

    @property
    def total_output_power(self) -> int | None:
        """Consumo actual: salida AC + salida DC."""
        if self.ac_output_power is None and self.dc_output_power is None:
            return None
        return int(self.ac_output_power or 0) + int(self.dc_output_power or 0)

    @property
    def total_input_power(self) -> int | None:
        """Entrada actual (red + solar)."""
        if self.ac_input_power is None and self.dc_input_power is None:
            return None
        return int(self.ac_input_power or 0) + int(self.dc_input_power or 0)

    @property
    def mode(self) -> str:
        return infer_mode(
            self.ac_output_power,
            self.dc_output_power,
            self.ac_input_power,
            self.dc_input_power,
        )

    def age(self, now: float | None = None) -> float:
        if not self.updated_at:
            return float("inf")
        return max(0.0, (now if now is not None else time.time()) - self.updated_at)


def _number(value: int | None) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def infer_mode(
    ac_output: int | None,
    dc_output: int | None,
    ac_input: int | None,
    dc_input: int | None,
) -> str:
    output = (ac_output or 0) + (dc_output or 0)
    if all(v is None for v in (ac_output, dc_output, ac_input, dc_input)):
        return MODE_UNKNOWN
    charging = (ac_input or 0) > INPUT_ON_THRESHOLD or (dc_input or 0) > INPUT_ON_THRESHOLD
    consuming = output > OUTPUT_ON_THRESHOLD
    if charging and consuming:
        return MODE_PASSTHROUGH
    if charging:
        return MODE_CHARGING
    if consuming:
        return MODE_DISCHARGING
    return MODE_IDLE


def band(percent: int | None) -> str:
    """Clasificación semafórica de la carga."""
    if percent is None:
        return "unknown"
    if percent >= 50:
        return "good"
    if percent >= 20:
        return "warn"
    return "bad"


def fmt_percent(percent: int | None) -> str:
    return f"{percent} %" if percent is not None else DASH


def fmt_power(watts: int | None) -> str:
    if watts is None:
        return DASH
    return f"{int(round(watts)):,}".replace(",", ".") + " W"


def fmt_power_compact(watts: int | None) -> str:
    """Formato corto para dibujar dentro del icono: 342, 1.2k."""
    if watts is None:
        return DASH
    value = int(round(watts))
    if abs(value) < 1000:
        return str(value)
    text = f"{value / 1000:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return text + "k"


def fmt_age(seconds: float) -> str:
    if seconds == float("inf"):
        return "nunca"
    seconds = int(seconds)
    if seconds < 60:
        return f"hace {seconds} s"
    if seconds < 3600:
        return f"hace {seconds // 60} min"
    return f"hace {seconds // 3600} h"


def device_label(status: Status, fallback: str = "") -> str:
    return status.device_name or status.device_type or fallback or "BLUETTI"


def state_label(status: Status) -> str:
    if not status.online:
        return "Sin conexión"
    return MODE_LABELS.get(status.mode, MODE_LABELS[MODE_UNKNOWN])


def summary_line(status: Status) -> str:
    """Línea corta tipo '87 % · 342 W' para el menú de la bandeja."""
    if not status.online:
        return "Sin conexión"
    parts = [fmt_percent(status.battery_percent)]
    output = status.total_output_power
    if output:
        parts.append(fmt_power(output))
    elif status.total_input_power:
        parts.append(f"+{fmt_power(status.total_input_power)}")
    return " · ".join(parts)


def tooltip(status: Status, fallback_name: str = "", poll_interval: int = 30) -> str:
    """Texto emergente del icono (límite de Windows: 127 caracteres)."""
    name = device_label(status, fallback_name)
    if not status.online:
        text = f"{name} · sin conexión"
        if status.updated_at:
            text += f" (última lectura {fmt_age(status.age())})"
        elif status.error:
            text += f" · {status.error}"
        return text[:122]

    parts = [name, fmt_percent(status.battery_percent)]
    if status.total_output_power is not None:
        parts.append(f"consumo {fmt_power(status.total_output_power)}")
    elif status.total_input_power is not None:
        parts.append(f"entrada {fmt_power(status.total_input_power)}")
    if status.mode in (MODE_CHARGING, MODE_PASSTHROUGH):
        if status.total_input_power:
            parts.append(f"cargando {fmt_power(status.total_input_power)}")
    parts.append(MODE_SHORT_LABELS.get(status.mode, ""))
    age = status.age()
    if age > max(90, poll_interval * 3):
        parts.append(f"desactualizado {fmt_age(age)}")
    return " · ".join(p for p in parts if p)[:120]


def detail_rows(status: Status) -> list[tuple[str, str]]:
    """Filas etiqueta/valor para el panel y la CLI."""
    rows: list[tuple[str, str]] = [
        ("Batería", fmt_percent(status.battery_percent)),
        ("Consumo (salida)", fmt_power(status.total_output_power)),
        ("  Salida AC", fmt_power(status.ac_output_power)),
        ("  Salida DC", fmt_power(status.dc_output_power)),
        ("Entrada (carga)", fmt_power(status.total_input_power)),
        ("  Entrada AC (red)", fmt_power(status.ac_input_power)),
        ("  Entrada DC (solar)", fmt_power(status.dc_input_power)),
        ("Estado", state_label(status)),
        ("Actualizado", fmt_age(status.age())),
    ]
    if status.device_type:
        rows.insert(0, ("Modelo", status.device_type))
    if status.device_sn:
        rows.insert(1, ("N.º de serie", status.device_sn))
    if status.address:
        rows.append(("Dirección BLE", status.address))
    if status.encrypted:
        rows.append(("Conexión", "BLE cifrada"))
    return rows
