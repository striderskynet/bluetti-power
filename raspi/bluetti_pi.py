#!/usr/bin/env python3
"""Monitor headless del BLUETTI AC180P para Raspberry Pi OS 64-bit.

Se conecta por Bluetooth LE, lee la carga y el consumo, los publica por HTTP
JSON y, opcionalmente, en un archivo de estado. Pensado para Raspberry Pi OS
Lite (sin interfaz gráfica) y para integrarse con Home Assistant u otros.

Uso:
  bluetti-pi scan                     # escanear equipos BLUETTI
  bluetti-pi setup                    # detectar el primero y guardar config
  bluetti-pi read                     # lectura puntual
  bluetti-pi run                      # daemon (lo usa systemd)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

try:  # como paquete (pruebas) o como script suelto (instalación)
    from . import bluetti_protocol as bp
except ImportError:  # pragma: no cover - ruta de ejecución directa
    import bluetti_protocol as bp  # type: ignore

__version__ = "0.1.0"

LOGGER = logging.getLogger("bluetti")

DEFAULT_CONFIG_SYSTEM = Path("/etc/bluetti-monitor/config.json")
DEFAULT_CONFIG_USER = Path("~/.config/bluetti-monitor/config.json")

TEXT = (
    "{percent}% · {watts} W · {state}"
    "{encrypted}{updated}"
)


# --------------------------------------------------------------------- config


@dataclass
class Config:
    address: str = ""
    name: str = ""
    encrypted_hint: bool | None = None
    interval_seconds: int = 60
    http_host: str = "0.0.0.0"
    http_port: int = 8099
    state_file: str = ""
    request_timeout: float = 50.0
    log_level: str = "INFO"

    def normalized(self) -> "Config":
        self.address = (self.address or "").strip().upper()
        self.name = (self.name or "").strip()
        self.interval_seconds = max(10, min(int(self.interval_seconds or 60), 3600))
        self.http_port = max(0, min(int(self.http_port or 0), 65535))
        self.request_timeout = max(10.0, min(float(self.request_timeout or 50.0), 180.0))
        self.log_level = (self.log_level or "INFO").upper()
        return self

    @classmethod
    def load(cls, path: Path) -> "Config":
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            LOGGER.warning("No se pudo leer %s: %s", path, exc)
            return cls()
        if not isinstance(raw, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in raw.items() if key in known}).normalized()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp, path)


def default_config_path() -> Path:
    if os.environ.get("BLUETTI_CONFIG"):
        return Path(os.environ["BLUETTI_CONFIG"]).expanduser()
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return DEFAULT_CONFIG_SYSTEM
    return DEFAULT_CONFIG_USER.expanduser()


# ------------------------------------------------------------------- logging


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for noisy in ("bleak", "dbus_fast", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# --------------------------------------------------------------- estado/HTTP


def publish_state_file(path_str: str, state: dict[str, Any]) -> None:
    if not path_str:
        return
    try:
        path = Path(path_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp, path)
    except OSError as exc:
        LOGGER.warning("No se pudo escribir %s: %s", path_str, exc)


async def http_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                       state_getter) -> None:
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        if not request_line:
            return
        parts = request_line.decode("latin-1").split()
        method = parts[0] if parts else ""
        path = parts[1].split("?")[0] if len(parts) > 1 else "/"
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if line in (b"\r\n", b"\n", b""):
                break

        status = "200 OK"
        if method != "GET":
            status = "405 Method Not Allowed"
            body = json.dumps({"error": "solo GET"}).encode()
        elif path in ("/status", "/status.json", "/"):
            body = json.dumps(state_getter(), ensure_ascii=False).encode()
        elif path == "/health":
            state = state_getter()
            body = json.dumps({"ok": bool(state.get("ok")),
                               "age_seconds": state.get("age_seconds")}).encode()
        else:
            status = "404 Not Found"
            body = json.dumps({"error": "no encontrado"}).encode()

        if status != "200 OK" and status != "404 Not Found":
            LOGGER.debug("HTTP %s %s", method, path)
        response = (
            f"HTTP/1.1 {status}\r\n"
            "Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode() + body
        writer.write(response)
        await writer.drain()
    except (asyncio.TimeoutError, ConnectionError, ValueError):
        pass
    except Exception as exc:  # noqa: BLE001 - el servidor nunca debe caerse
        LOGGER.debug("Error HTTP: %s", exc)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------- daemon


async def run_daemon(config: Config) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop(*_args) -> None:
        if not stop.is_set():
            LOGGER.info("Deteniendo…")
            stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, request_stop)
        except (NotImplementedError, RuntimeError, ValueError):
            try:
                signal.signal(sig, lambda *_: loop.call_soon_threadsafe(request_stop))
            except (ValueError, OSError):
                pass

    state: dict[str, Any] = {
        "ok": False,
        "state": "iniciando",
        "error": "sin datos todavía",
        "updated_at": None,
        "age_seconds": None,
        "interval_seconds": config.interval_seconds,
        "device_type": None,
        "encrypted": None,
    }
    state_lock = asyncio.Lock()

    def current_state() -> dict[str, Any]:
        return state

    server = None
    if config.http_port > 0:
        try:
            server = await asyncio.start_server(
                lambda r, w: http_handler(r, w, current_state),
                config.http_host,
                config.http_port,
            )
            LOGGER.info("HTTP en http://%s:%d/status", config.http_host, config.http_port)
        except OSError as exc:
            LOGGER.error("No se pudo abrir el puerto HTTP %d: %s", config.http_port, exc)
            server = None

    LOGGER.info(
        "Monitor iniciado: %s (cada %d s)",
        config.address or config.name or "SIN DISPOSITIVO CONFIGURADO",
        config.interval_seconds,
    )

    try:
        last_good: dict[str, Any] | None = None
        last_good_time = 0.0
        while not stop.is_set():
            started = loop.time()
            if not config.address and not config.name:
                reading = bp.Reading(
                    error="sin dispositivo configurado (ejecuta 'bluetti-pi setup')",
                    timestamp=time.time(),
                )
            else:
                reading = await bp.read_status(
                    config.address,
                    config.name,
                    config.encrypted_hint,
                    timeout=config.request_timeout,
                )

            if reading.ok:
                LOGGER.info(
                    "%d%% · %d W · %s%s",
                    reading.percent,
                    reading.total_out,
                    reading.state,
                    " · BLE cifrado" if reading.encrypted else "",
                )
                new_state = reading.as_dict()
                last_good = dict(new_state)
                last_good_time = reading.timestamp
            else:
                LOGGER.warning("Sin lectura: %s", reading.error)
                if last_good is not None:
                    new_state = dict(last_good)
                    new_state.update(
                        ok=False,
                        error=reading.error,
                        state="sin conexión",
                        stale=True,
                        age_seconds=round(max(0.0, time.time() - last_good_time), 1),
                    )
                else:
                    new_state = reading.as_dict()
                    new_state["stale"] = True

            new_state["server_time"] = bp.iso_time(time.time())
            new_state["interval_seconds"] = config.interval_seconds
            new_state["state_file"] = config.state_file or None
            async with state_lock:
                state.clear()
                state.update(new_state)
            publish_state_file(config.state_file, new_state)

            elapsed = loop.time() - started
            if reading.ok:
                delay = max(10.0, config.interval_seconds - elapsed)
            elif not config.address and not config.name:
                delay = 30.0
            else:
                delay = max(10.0, min(60.0, elapsed))
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
    finally:
        if server is not None:
            server.close()
            try:
                await server.wait_closed()
            except Exception:  # noqa: BLE001
                pass
        LOGGER.info("Monitor detenido")
    return 0


# --------------------------------------------------------------------- comandos


def cmd_scan(args: argparse.Namespace) -> int:
    try:
        hits = asyncio.run(bp.scan(args.timeout))
    except bp.BluettiError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not hits:
        print("No se encontró ningún equipo BLUETTI. Enciéndelo y acércalo.")
        return 1
    print(f"{'DIRECCIÓN':<20} {'SEÑAL':>10}  NOMBRE")
    for hit in hits:
        signal_str = f"{hit.rssi} dBm" if hit.rssi is not None else "?"
        print(f"{hit.address:<20} {signal_str:>10}  {hit.name}")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    path = Path(args.config).expanduser() if args.config else default_config_path()
    try:
        hits = asyncio.run(bp.scan(args.timeout))
    except bp.BluettiError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    address = (args.address or "").strip().upper()
    selected = None
    if address:
        selected = next((hit for hit in hits if hit.address.upper() == address), None)
        if selected is None:
            print(f"Aviso: {address} no apareció en el escaneo; se guarda igualmente.")
    elif hits:
        selected = hits[0]
        address = selected.address
    else:
        print("No se encontró ningún equipo BLUETTI. Enciéndelo y reintenta.")
        return 1

    config = Config.load(path)
    config.address = address
    config.name = args.name or (selected.name if selected else "")
    config.encrypted_hint = selected.encrypted if selected else None
    config.save(path)
    print(f"Configuración guardada en {path}")
    print(f"  equipo: {config.name or '(sin nombre)'}  {config.address}")
    print("Siguiente paso: sudo systemctl restart bluetti-monitor")
    print("Comprueba:      curl http://localhost:%d/status" % config.http_port)
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    config = Config.load(Path(args.config).expanduser()) if args.config else Config()
    address = (args.address or config.address).strip().upper()
    name = args.name or config.name
    reading = asyncio.run(
        bp.read_status(address, name, config.encrypted_hint, timeout=args.timeout)
    )
    if args.json:
        print(json.dumps(reading.as_dict(), indent=2, ensure_ascii=False))
    elif reading.ok:
        print(TEXT.format(
            percent=reading.percent,
            watts=reading.total_out,
            state=reading.state,
            encrypted=" · BLE cifrado" if reading.encrypted else "",
            updated=f" · {bp.iso_time(reading.timestamp)}",
        ))
        print(f"  modelo: {reading.device_type}  dir: {reading.address}")
        print(f"  salida AC {reading.ac_out} W · salida DC {reading.dc_out} W")
        print(f"  entrada AC {reading.ac_in} W · entrada DC {reading.dc_in} W")
    else:
        print(f"Error: {reading.error}", file=sys.stderr)
    return 0 if reading.ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    path = Path(args.config).expanduser() if args.config else default_config_path()
    config = Config.load(path)
    if args.address:
        config.address = args.address.strip().upper()
    if args.name:
        config.name = args.name.strip()
    if args.interval:
        config.interval_seconds = args.interval
    if args.http_port is not None:
        config.http_port = args.http_port
    if args.state_file:
        config.state_file = args.state_file
    config.normalized()
    setup_logging(config.log_level)
    LOGGER.info("bluetti-pi %s · config: %s", __version__, path if path.exists() else "(por defecto)")
    try:
        return asyncio.run(run_daemon(config))
    except KeyboardInterrupt:
        return 0


# ------------------------------------------------------------------------ CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bluetti-pi",
        description="Monitor headless del BLUETTI AC180P por Bluetooth LE.",
    )
    parser.add_argument("--version", action="version", version=f"bluetti-pi {__version__}")
    sub = parser.add_subparsers(dest="command")

    scan_p = sub.add_parser("scan", help="escanea equipos BLUETTI cercanos")
    scan_p.add_argument("-t", "--timeout", type=float, default=10.0)
    scan_p.set_defaults(func=cmd_scan)

    setup_p = sub.add_parser("setup", help="detecta el equipo y guarda la configuración")
    setup_p.add_argument("-a", "--address")
    setup_p.add_argument("-n", "--name")
    setup_p.add_argument("-c", "--config")
    setup_p.add_argument("-t", "--timeout", type=float, default=10.0)
    setup_p.set_defaults(func=cmd_setup)

    read_p = sub.add_parser("read", help="hace una lectura puntual")
    read_p.add_argument("-a", "--address")
    read_p.add_argument("-n", "--name")
    read_p.add_argument("-c", "--config")
    read_p.add_argument("-t", "--timeout", type=float, default=50.0)
    read_p.add_argument("--json", action="store_true")
    read_p.set_defaults(func=cmd_read)

    run_p = sub.add_parser("run", help="inicia el daemon")
    run_p.add_argument("-c", "--config")
    run_p.add_argument("-a", "--address")
    run_p.add_argument("-n", "--name")
    run_p.add_argument("-i", "--interval", type=int)
    run_p.add_argument("--http-port", type=int)
    run_p.add_argument("-s", "--state-file")
    run_p.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        return cmd_run(parser.parse_args((argv or []) + ["run"]))
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
