"""Datos simulados para probar la interfaz sin tener el equipo cerca (--demo)."""

from __future__ import annotations

import math
import time

from .status import Status

_CYCLE_CHARGE = 45.0  # segundos cargando
_CYCLE_DISCHARGE = 75.0  # segundos descargando


def demo_status(elapsed: float | None = None) -> Status:
    """Genera un estado verosímil que va cargando y descargando en bucle."""
    now = time.time()
    t = (elapsed if elapsed is not None else now) % (_CYCLE_CHARGE + _CYCLE_DISCHARGE)

    charging = t < _CYCLE_CHARGE
    if charging:
        phase = t / _CYCLE_CHARGE
        percent = 38 + int(54 * phase)
        ac_input = int(520 + 80 * math.sin(t * 1.3))
        dc_input = 0
        ac_output = 18 if percent < 90 else 0
        dc_output = 7
    else:
        phase = (t - _CYCLE_CHARGE) / _CYCLE_DISCHARGE
        percent = 92 - int(56 * phase)
        ac_input = 0
        dc_input = 0
        ac_output = int(260 + 120 * math.sin(t * 0.9))
        dc_output = 34

    return Status(
        battery_percent=max(0, min(100, percent)),
        ac_output_power=ac_output,
        dc_output_power=dc_output,
        ac_input_power=ac_input,
        dc_input_power=dc_input,
        device_type="AC180P",
        device_sn="DEMO00000000",
        device_name="AC180P (demo)",
        online=True,
        source="demo",
        updated_at=now,
    )
