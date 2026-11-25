"""Sondeo periódico del equipo en un hilo propio con un único event loop asyncio."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from dataclasses import replace
from typing import Callable

from .ble import BluettiError, read_status
from .config import Config
from .status import Status

_LOGGER = logging.getLogger(__name__)


class StatusStore:
    """Último estado conocido e historial, seguro entre hilos."""

    def __init__(self, history_size: int = 720) -> None:
        self._lock = threading.Lock()
        self._status = Status(updated_at=0.0)
        self._history: deque[tuple[float, int | None, int | None]] = deque(maxlen=history_size)

    def update(self, status: Status) -> None:
        with self._lock:
            self._status = status
            if status.online:
                self._history.append(
                    (status.updated_at or time.time(), status.battery_percent, status.total_output_power)
                )

    def snapshot(self) -> Status:
        with self._lock:
            return self._status

    def history(self) -> list[tuple[float, int | None, int | None]]:
        with self._lock:
            return list(self._history)


class Poller:
    """Lee el equipo cada ``poll_interval`` segundos y publica el resultado."""

    def __init__(
        self,
        config: Config,
        store: StatusStore,
        on_status: Callable[[Status], None],
        on_learned_encryption: Callable[[bool | None], None] | None = None,
        on_address: Callable[[str], None] | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._on_status = on_status
        self._on_learned = on_learned_encryption
        self._on_address = on_address
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._failures = 0
        self._thread = threading.Thread(target=self._run, name="bluetti-poller", daemon=True)

    # -- API pública -----------------------------------------------------
    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=timeout)

    def update_config(self, config: Config, wake: bool = True) -> None:
        with self._lock:
            self._config = config
        if wake:
            self._wake.set()

    def refresh_now(self) -> None:
        self._wake.set()

    def config(self) -> Config:
        with self._lock:
            return self._config

    # -- interno ---------------------------------------------------------
    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _LOGGER.info("Sondeo iniciado (cada %s s)", self.config().poll_interval)
        try:
            while not self._stop.is_set():
                config = self.config()
                self._wake.clear()

                if not config.address and not config.demo:
                    # Aún no hay equipo elegido: no tiene sentido abrir el BLE.
                    self._store.update(
                        Status(
                            online=False,
                            error="sin dispositivo configurado",
                            device_name=config.device_name or config.device_type,
                            device_type=config.device_type,
                        )
                    )
                    self._wake.wait(timeout=30)
                    continue

                started = time.monotonic()
                status = self._poll_once(loop, config)
                elapsed = time.monotonic() - started
                self._store.update(status)
                try:
                    self._on_status(status)
                except Exception:  # noqa: BLE001 - nunca matar el hilo por la UI
                    _LOGGER.exception("Error actualizando la interfaz")

                if status.online:
                    self._failures = 0
                    if (
                        status.source == "ble"
                        and config.encryption == "auto"
                        and config.learned_encryption is None
                        and self._on_learned is not None
                    ):
                        self._on_learned(status.encrypted)
                    if (
                        status.address
                        and self._on_address is not None
                        and status.address.upper() != (config.address or "").upper()
                    ):
                        self._on_address(status.address)
                else:
                    self._failures += 1
                    if (
                        config.learned_encryption is not None
                        and self._failures >= 3
                        and self._on_learned is not None
                    ):
                        _LOGGER.warning("Se olvida el modo de cifrado tras 3 fallos")
                        self._on_learned(None)

                if status.online:
                    # Mantiene la cadencia configurada descontando lo que tardó la lectura.
                    delay = max(10.0, config.poll_interval - elapsed)
                else:
                    delay = min(60, 10 * max(1, self._failures))
                if self._wake.wait(timeout=delay):
                    self._wake.clear()
        finally:
            loop.close()
            _LOGGER.info("Sondeo detenido")

    def _poll_once(self, loop: asyncio.AbstractEventLoop, config: Config) -> Status:
        started = time.monotonic()
        try:
            status = loop.run_until_complete(read_status(config))
            _LOGGER.debug("Lectura en %.1f s: %s", time.monotonic() - started, status)
            return status
        except BluettiError as exc:
            _LOGGER.info("Sin lectura: %s", exc)
            return self._offline_status(config, str(exc))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("Fallo inesperado leyendo el equipo")
            return self._offline_status(config, f"error inesperado: {exc}")

    def _offline_status(self, config: Config, error: str) -> Status:
        last = self._store.snapshot()
        return replace(
            last,
            online=False,
            error=error,
            source="ble",
            device_name=last.device_name or config.device_name or config.device_type,
            device_type=last.device_type or config.device_type,
        )
