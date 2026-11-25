"""Comunicación BLE con el BLUETTI AC180P (protocolo MODBUS de los equipos V2).

Usa la librería ``bluetti-bt-lib`` (Patrick762, MIT), que implementa el
protocolo MODBUS RTU sobre BLE y el handshake cifrado que usan algunas
unidades.  El AC180P responde en las características ff02 (escritura) y ff01
(notificaciones) con tramas ``01 03 <dir> <cantidad> <crc>``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from bleak import BleakScanner
from bluetti_bt_lib.base_devices import BaseDeviceV2
from bluetti_bt_lib.bluetooth.device_reader import DeviceReader, DeviceReaderConfig
from bluetti_bt_lib.bluetooth.device_recognizer import recognize_device
from bluetti_bt_lib.devices import DEVICES
from bluetti_bt_lib.registers import ReadableRegisters
from bluetti_bt_lib.utils.device_builder import build_device
from bluetti_bt_lib.utils.device_info import get_type_by_bt_name

from .config import Config
from .demo import demo_status
from .status import Status

_LOGGER = logging.getLogger(__name__)

#: Identificador de compañía que usa BLUETTI en el anuncio BLE ("BL").
BLUETTI_COMPANY_ID = 0x4C42

#: Registros a leer.  Se leen por separado (como hace la librería oficial) para
#: no depender de lecturas MODBUS multi-registro largas.
#: 102 = SOC, 110..115 = modelo, 140/142 = salida DC/AC, 144/146 = entrada DC/AC.
READ_REGISTERS = (
    ReadableRegisters(102, 1),
    ReadableRegisters(110, 6),
    ReadableRegisters(140, 1),
    ReadableRegisters(142, 1),
    ReadableRegisters(144, 1),
    ReadableRegisters(146, 1),
)

#: Modelos V2 soportados por este mapa de registros.
SUPPORTED_TYPES: set[str] = {
    name for name, cls in DEVICES.items() if issubclass(cls, BaseDeviceV2)
}

SCAN_TIMEOUT = 6.0
READ_TIMEOUT = 50.0
NOT_FOUND_MESSAGE = "equipo no encontrado (¿está encendido y cerca?)"
_NO_DEVICE_MESSAGE = "no hay ningún dispositivo configurado"


class BluettiError(RuntimeError):
    """Error de comunicación con el equipo."""


@dataclass
class DiscoveredDevice:
    address: str
    name: str
    rssi: int | None
    device_type: str | None
    supported: bool
    encrypted: bool | None = None

    def label(self) -> str:
        kind = self.device_type or ("BLUETTI" if self.supported else "")
        name = self.name or "(sin nombre)"
        rssi = f"{self.rssi} dBm" if self.rssi is not None else "?"
        extra = f"  ·  {kind}" if kind else ""
        secure = "" if self.encrypted is None else ("  ·  cifrado" if self.encrypted else "  ·  sin cifrar")
        return f"{name}  ·  {self.address}  ·  {rssi}{extra}{secure}"


@dataclass
class DetectedDevice:
    device_type: str
    encrypted: bool
    serial: str = ""


def encryption_from_manufacturer_data(manufacturer_data: dict | None) -> bool | None:
    """Deduce del anuncio BLE si el canal viene cifrado.

    BLUETTI anuncia ``BLUETTI`` (sin cifrar) o ``BLUETTF`` (cifrado).
    """
    if not manufacturer_data:
        return None
    for value in manufacturer_data.values():
        try:
            payload = bytes(value)
        except TypeError:
            continue
        if b"BLUETTF" in payload:
            return True
        if b"BLUETTI" in payload:
            return False
    return None


async def _discover() -> dict:
    try:
        return await BleakScanner.discover(timeout=SCAN_TIMEOUT, return_adv=True)
    except Exception as exc:  # noqa: BLE001 - se informa al usuario
        raise BluettiError(f"no se pudo usar el Bluetooth: {exc}") from exc


def _type_from_name(name: str) -> str | None:
    """Deduce el modelo a partir del prefijo del nombre BLE anunciado."""
    upper = name.upper()
    for device_type in sorted(SUPPORTED_TYPES, key=len, reverse=True):
        if upper.startswith(device_type.upper()):
            return device_type
    return None


async def scan_devices(timeout: float = 8.0) -> list[DiscoveredDevice]:
    """Escanea dispositivos BLE cercanos y marca los que son BLUETTI."""
    try:
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    except Exception as exc:  # noqa: BLE001
        raise BluettiError(f"no se pudo usar el Bluetooth: {exc}") from exc

    devices: list[DiscoveredDevice] = []
    for address, (device, advertisement) in found.items():
        name = (device.name or advertisement.local_name or "").strip()
        device_type = get_type_by_bt_name(name) if name else None
        if device_type is None and name:
            # Algunos equipos no añaden el número de serie al nombre.
            device_type = _type_from_name(name)
        supported = bool(
            device_type
            or name.upper().startswith("PBOX")
            or name.upper().startswith("BLUETTI")
        )
        devices.append(
            DiscoveredDevice(
                address=address,
                name=name,
                rssi=getattr(advertisement, "rssi", None),
                device_type=device_type,
                supported=supported,
                encrypted=encryption_from_manufacturer_data(
                    getattr(advertisement, "manufacturer_data", None)
                ),
            )
        )
    devices.sort(key=lambda d: (not d.supported, not d.name, d.name.lower()))
    return devices


@dataclass
class _Target:
    address: str
    encrypted: bool | None = None
    name: str = ""


def _advertised_name(device, advertisement) -> str:
    return (getattr(device, "name", None) or getattr(advertisement, "local_name", None) or "").strip()


def _match_device(found: dict, cfg: Config) -> _Target | None:
    """Elige el equipo anunciado: primero por dirección, luego por nombre/modelo."""
    def hint(advertisement) -> bool | None:
        return encryption_from_manufacturer_data(getattr(advertisement, "manufacturer_data", None))

    wanted = (cfg.address or "").upper()
    if wanted:
        for address, (device, advertisement) in found.items():
            if address.upper() == wanted:
                return _Target(address, hint(advertisement), _advertised_name(device, advertisement))

    wanted_name = (cfg.device_name or "").strip().upper()
    model = (cfg.device_type or "").strip().upper()
    candidates: list[tuple[int, int, str, bool | None]] = []
    for address, (device, advertisement) in found.items():
        name = _advertised_name(device, advertisement)
        if not name:
            continue
        upper = name.upper()
        if wanted_name and upper == wanted_name:
            score = 3
        elif wanted_name and upper.startswith(wanted_name):
            score = 2
        elif model and upper.startswith(model):
            score = 1
        else:
            continue
        rssi = getattr(advertisement, "rssi", None) or -999
        candidates.append((score, rssi, address, hint(advertisement)))

    if not candidates:
        return None
    candidates.sort(key=lambda candidate: (candidate[0], candidate[1]), reverse=True)
    _score, _rssi, address, encrypted = candidates[0]
    for addr, (device, advertisement) in found.items():
        if addr == address:
            return _Target(address, encrypted, _advertised_name(device, advertisement))
    return None


async def _find_target(cfg: Config) -> _Target | None:
    found = await _discover()
    return _match_device(found, cfg)


def _encryption_attempts(cfg: Config, hint: bool | None) -> list[bool]:
    if cfg.encryption == "on":
        return [True]
    if cfg.encryption == "off":
        return [False]
    if cfg.learned_encryption is not None:
        return [cfg.learned_encryption]
    if hint is not None:
        return [hint]
    return [False, True]


def _build_device(device_type: str):
    """Crea la definición del equipo resolviendo el modelo sin distinguir mayúsculas."""
    name = (device_type or "AC180P").strip()
    canonical = next((key for key in DEVICES if key.upper() == name.upper()), name)
    built = build_device(canonical + "12345678")
    if built is None:
        raise BluettiError(f"modelo no soportado: {device_type}")
    return built


async def _read_registers(
    address: str,
    device_type: str,
    use_encryption: bool,
    timeout: float = READ_TIMEOUT,
    ble_client=None,
) -> dict | None:
    """Realiza una lectura de registros con la librería (conexión por lectura)."""
    built = _build_device(device_type)
    reader = DeviceReader(
        address,
        built,
        asyncio.Future,
        DeviceReaderConfig(timeout=timeout, use_encryption=use_encryption),
        ble_client=ble_client,
    )
    data = await reader.read(only_registers=list(READ_REGISTERS))
    if data:
        _LOGGER.debug("Lectura BLE (cifrado=%s): %s", use_encryption, data)
    return data


def _valid_payload(data: dict | None) -> bool:
    """Comprueba que la respuesta parece un equipo BLUETTI V2 real."""
    if not data:
        return False
    percent = data.get("total_battery_percent")
    device_type = data.get("device_type")
    if not isinstance(percent, (int, float)) or not (0 <= int(percent) <= 100):
        return False
    if not isinstance(device_type, str) or not device_type:
        return False
    # Un equipo cifrado leído en claro devuelve basura; el modelo no será válido.
    return get_type_by_bt_name(device_type + "12345678") is not None


def status_from_data(data: dict, cfg: Config, encrypted: bool, address: str = "") -> Status:
    """Convierte el diccionario de campos de la librería en un :class:`Status`."""

    def number(key: str) -> int | None:
        value = data.get(key)
        if value is None:
            return None
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return None

    device_type = str(data.get("device_type") or cfg.device_type or "").strip()
    serial = data.get("device_sn")
    serial_text = str(serial) if serial not in (None, "") else ""

    return Status(
        battery_percent=number("total_battery_percent"),
        ac_output_power=number("ac_output_power"),
        dc_output_power=number("dc_output_power"),
        ac_input_power=number("ac_input_power"),
        dc_input_power=number("dc_input_power"),
        device_type=device_type,
        device_sn=serial_text,
        device_name=cfg.device_name or device_type or cfg.device_type,
        encrypted=encrypted,
        address=address,
        online=True,
        source="ble",
        updated_at=time.time(),
    )


async def _try_reads(
    cfg: Config, address: str, hint: bool | None, timeout: float
) -> tuple[dict, bool]:
    failures: list[str] = []
    for encrypted in _encryption_attempts(cfg, hint):
        data = await _read_registers(address, cfg.device_type, encrypted, timeout)
        if _valid_payload(data) and data is not None:
            return data, encrypted
        failures.append("cifrada" if encrypted else "sin cifrar")
    detail = f" ({', '.join(failures)})" if failures else ""
    raise BluettiError(f"sin respuesta válida del equipo{detail}")


async def _read_payloads(cfg: Config, timeout: float) -> tuple[dict, bool, str]:
    """Devuelve (campos, cifrado, dirección usada).

    Si la dirección guardada ya no existe (algunos equipos usan direcciones
    aleatorias que cambian), se busca de nuevo por nombre/modelo y se actualiza.
    """
    resolved = cfg.address
    hint: bool | None = None
    if not resolved or (cfg.encryption == "auto" and cfg.learned_encryption is None):
        target = await _find_target(cfg)
        if target is None and not resolved:
            raise BluettiError(NOT_FOUND_MESSAGE)
        if target is not None:
            resolved = target.address
            hint = target.encrypted

    try:
        data, encrypted = await _try_reads(cfg, resolved, hint, timeout)
        return data, encrypted, resolved
    except BluettiError as first_error:
        # La dirección puede haber cambiado: reintentamos con lo que se anuncie ahora.
        target = await _find_target(cfg)
        if target is None:
            raise BluettiError(NOT_FOUND_MESSAGE) from first_error
        if target.address.upper() != (resolved or "").upper():
            data, encrypted = await _try_reads(cfg, target.address, target.encrypted, timeout)
            return data, encrypted, target.address
        raise


async def read_status(cfg: Config, timeout: float = READ_TIMEOUT) -> Status:
    """Lee el estado del equipo probando el modo de cifrado que corresponda."""
    cfg = cfg.normalized()
    if cfg.demo:
        return demo_status()
    if not cfg.address and not cfg.device_name:
        raise BluettiError(_NO_DEVICE_MESSAGE)

    data, encrypted, address = await _read_payloads(cfg, timeout)
    return status_from_data(data, cfg, encrypted, address)


async def read_raw(cfg: Config, timeout: float = READ_TIMEOUT) -> tuple[dict, bool, str]:
    """Lectura de diagnóstico: devuelve los campos crudos, cifrado y dirección."""
    cfg = cfg.normalized()
    if not cfg.address and not cfg.device_name:
        raise BluettiError(_NO_DEVICE_MESSAGE)
    return await _read_payloads(cfg, timeout)


async def detect_device(address: str) -> DetectedDevice:
    """Detecta modelo y cifrado con el reconocedor oficial de la librería."""
    try:
        result = await recognize_device(address, asyncio.Future)
    except Exception as exc:  # noqa: BLE001
        raise BluettiError(f"no se pudo identificar el equipo: {exc}") from exc
    if result is None:
        raise BluettiError("el equipo no respondió al reconocimiento")
    serial = str(result.sn) if getattr(result, "sn", None) else ""
    return DetectedDevice(
        device_type=result.name,
        encrypted=bool(result.encrypted),
        serial=serial,
    )


def read_status_sync(cfg: Config, timeout: float = READ_TIMEOUT) -> Status:
    """Variante síncrona para la CLI."""
    return asyncio.run(read_status(cfg, timeout=timeout))


def scan_sync(timeout: float = 8.0) -> list[DiscoveredDevice]:
    return asyncio.run(scan_devices(timeout=timeout))
