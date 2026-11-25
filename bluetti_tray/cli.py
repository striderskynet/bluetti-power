"""Punto de entrada: bandeja (por defecto) y utilidades de diagnóstico."""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import logging
import sys
import time
from dataclasses import replace
from logging.handlers import RotatingFileHandler

from . import __version__
from .ble import (
    BluettiError,
    detect_device,
    read_raw,
    read_status_sync,
    scan_devices,
)
from .config import Config, normalize_address
from .paths import config_path, log_path
from .status import detail_rows

_LOGGER = logging.getLogger(__name__)


def setup_logging(config: Config) -> None:
    level = getattr(logging, config.log_level, logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    try:
        handler = RotatingFileHandler(log_path(), maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(fmt)
        root.addHandler(handler)
    except OSError:
        pass
    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)
    for noisy in ("bleak", "winrt", "bleak_retry_connector", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _fatal_error(message: str) -> None:
    _LOGGER.error("%s", message)
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "BluettiTray", 0x10)
    except Exception:  # noqa: BLE001
        print(message, file=sys.stderr)


def _acquire_single_instance() -> bool:
    """Evita dos iconos de bandeja a la vez (el AC180P admite una sola conexión)."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\BluettiTraySingleton")
    if not handle:
        return True
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return False
    _KEEP_ALIVE.append(handle)
    return True


_KEEP_ALIVE: list = []


# -- comandos -------------------------------------------------------------
def cmd_run(args: argparse.Namespace) -> int:
    if not _acquire_single_instance():
        ctypes.windll.user32.MessageBoxW(
            None,
            "BluettiTray ya se está ejecutando.\nBusca el icono en la bandeja del sistema.",
            "BluettiTray",
            0x40,
        )
        return 0

    config = Config.load()
    if args.demo:
        config = replace(config, demo=True)
    setup_logging(config)
    _LOGGER.info("BluettiTray %s · configuración: %s", __version__, config_path())

    from .tray import TrayApp

    try:
        TrayApp(config, open_panel=args.panel).run()
    except Exception as exc:  # noqa: BLE001
        _LOGGER.exception("Fallo fatal iniciando la bandeja")
        _fatal_error(f"No se pudo iniciar BluettiTray:\n{exc}")
        return 1
    return 0


def _load_config(args: argparse.Namespace) -> Config:
    config = Config.load()
    if getattr(args, "demo", False):
        config = replace(config, demo=True)
    if getattr(args, "address", None):
        config = replace(config, address=normalize_address(args.address))
    if getattr(args, "type", None):
        config = replace(config, device_type=args.type.strip())
    if getattr(args, "encryption", None):
        config = replace(config, encryption=args.encryption)
    return config.normalized()


def cmd_scan(args: argparse.Namespace) -> int:
    config = Config.load()
    setup_logging(config)
    print(f"Escaneando {args.timeout:.0f} s…")
    try:
        devices = asyncio.run(scan_devices(args.timeout))
    except BluettiError as exc:
        print(f"Error: {exc}")
        return 1
    if not devices:
        print("No se encontró ningún dispositivo BLE.")
        return 0
    for device in devices:
        flags = []
        if device.device_type:
            flags.append("BLUETTI")
        if device.encrypted is True:
            flags.append("cifrado")
        if device.encrypted is False:
            flags.append("sin cifrar")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        rssi = f"{device.rssi:>4} dBm" if device.rssi is not None else "    ?    "
        print(f"{device.address}  {rssi}  {device.name or '(sin nombre)'}{suffix}")
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    config = _load_config(args)
    setup_logging(config)
    print(f"Dispositivo: {config.address or '(sin configurar)'} · modelo {config.device_type}")
    try:
        status = read_status_sync(config, timeout=args.timeout)
    except BluettiError as exc:
        print(f"Error: {exc}")
        return 1
    for label, value in detail_rows(status):
        print(f"{label:<22} {value}")
    print(f"{'Cifrado':<22} {'sí' if status.encrypted else 'no'}")
    if args.raw:
        try:
            data, encrypted, address = asyncio.run(read_raw(config, timeout=args.timeout))
        except BluettiError as exc:
            print(f"Error leyendo campos crudos: {exc}")
            return 1
        print(f"\nDirección BLE usada: {address}")
        print("Campos crudos:")
        for key in sorted(data):
            print(f"  {key} = {data[key]!r}")
        print(f"  (cifrado={encrypted})")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    config = _load_config(args)
    setup_logging(config)
    print("Leyendo en bucle (Ctrl+C para salir)…")
    try:
        while True:
            started = time.time()
            try:
                status = read_status_sync(config, timeout=args.timeout)
                print(
                    f"{time.strftime('%H:%M:%S')}  {status.battery_percent}%  "
                    f"salida {status.total_output_power} W  entrada {status.total_input_power} W  "
                    f"{status.mode}  ({time.time() - started:.1f} s)"
                )
            except BluettiError as exc:
                print(f"{time.strftime('%H:%M:%S')}  sin lectura: {exc} ({time.time() - started:.1f} s)")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


def cmd_detect(args: argparse.Namespace) -> int:
    config = Config.load()
    setup_logging(config)
    mac = normalize_address(args.address) if args.address else config.address
    if not mac:
        print("Indica una dirección con --address AA:BB:CC:DD:EE:FF")
        return 2
    print(f"Identificando {mac} (puede tardar ~30 s)…")
    try:
        detected = asyncio.run(detect_device(mac))
    except BluettiError as exc:
        print(f"Error: {exc}")
        return 1
    print(f"Modelo:   {detected.device_type}")
    print(f"Cifrado:  {'sí' if detected.encrypted else 'no'}")
    if detected.serial:
        print(f"Serie:    {detected.serial}")
    print(f"\nPuedes guardarlo con: python main.py read --address {mac} --type {detected.device_type}")
    return 0


# -- main -----------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="BluettiTray",
        description="Indicador de bandeja con la carga y el consumo de un BLUETTI AC180P por Bluetooth.",
    )
    parser.add_argument("--version", action="version", version=f"BluettiTray {__version__}")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="inicia el icono de la bandeja (predeterminado)")
    run_p.add_argument("--demo", action="store_true", help="datos simulados, sin Bluetooth")
    run_p.add_argument("--panel", action="store_true", help="abre el panel de estado al arrancar")
    run_p.set_defaults(func=cmd_run)

    scan_p = sub.add_parser("scan", help="escanea dispositivos BLE cercanos")
    scan_p.add_argument("-t", "--timeout", type=float, default=8.0)
    scan_p.set_defaults(func=cmd_scan)

    read_p = sub.add_parser("read", help="lee el estado una vez")
    read_p.add_argument("-m", "--address", help="dirección Bluetooth (MAC)")
    read_p.add_argument("-t", "--type", help="modelo, p. ej. AC180P")
    read_p.add_argument("-e", "--encryption", choices=("auto", "on", "off"))
    read_p.add_argument("--timeout", type=float, default=50.0)
    read_p.add_argument("--raw", action="store_true", help="muestra todos los campos crudos")
    read_p.add_argument("--demo", action="store_true")
    read_p.set_defaults(func=cmd_read)

    watch_p = sub.add_parser("watch", help="lee en bucle (diagnóstico)")
    watch_p.add_argument("-m", "--address")
    watch_p.add_argument("-t", "--type")
    watch_p.add_argument("-e", "--encryption", choices=("auto", "on", "off"))
    watch_p.add_argument("--interval", type=float, default=30.0)
    watch_p.add_argument("--timeout", type=float, default=50.0)
    watch_p.set_defaults(func=cmd_watch)

    detect_p = sub.add_parser("detect", help="identifica modelo y cifrado de un equipo")
    detect_p.add_argument("-m", "--address")
    detect_p.set_defaults(func=cmd_detect)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - consolas antiguas
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args((argv or []) + ["run"])
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
