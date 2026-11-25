"""Aplicación de bandeja: coordina el sondeo BLE, el icono y las ventanas."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import replace

import pystray
from pystray import Menu, MenuItem

from . import autostart
from .ble import SUPPORTED_TYPES
from .config import Config, normalize_address
from .icon import render_icon
from .paths import log_path
from .poller import Poller, StatusStore
from .status import Status, fmt_power, summary_line, tooltip
from .ui import UiThread

_LOGGER = logging.getLogger(__name__)

ICON_SIZE = 64
ICON_METRICS = {
    "percent": "% de carga",
    "power": "Consumo (W)",
    "both": "% y W",
}


class TrayApp:
    """Icono en la bandeja del sistema con el estado del AC180P."""

    supported_types = SUPPORTED_TYPES

    def __init__(self, config: Config, open_panel: bool = False) -> None:
        self._lock = threading.RLock()
        self.config = config.normalized()
        self.store = StatusStore()
        self.ui = UiThread(self)
        self._open_panel_on_start = open_panel
        self.poller = Poller(
            self.config,
            self.store,
            on_status=self._on_status,
            on_learned_encryption=self._on_learned_encryption,
            on_address=self._on_address_changed,
        )
        self.icon: pystray.Icon | None = None
        self._low_notified = False
        self._full_notified = False
        self._quitting = False

    # -- ciclo de vida ----------------------------------------------------
    def run(self) -> None:
        self.ui.start()
        self.poller.start()
        self.icon = pystray.Icon(
            "BluettiTray",
            icon=render_icon(
                Status(online=False), self.config.icon_metric, ICON_SIZE, self.config.max_output_power
            ),
            title="BLUETTI — conectando…",
            menu=self._menu(),
        )
        if not self.config.address and not self.config.demo:
            threading.Timer(0.8, self.ui.open_device_dialog).start()
        if self._open_panel_on_start:
            threading.Timer(0.8, self.ui.open_panel).start()
        try:
            self.icon.run()
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        self._quitting = True
        self.poller.stop()
        self.ui.stop()
        with self._lock:
            try:
                self.config.save()
            except OSError:
                _LOGGER.exception("No se pudo guardar la configuración")

    def quit_app(self, _icon=None, _item=None) -> None:
        self._quitting = True
        with self._lock:
            try:
                self.config.save()
            except OSError:
                _LOGGER.exception("No se pudo guardar la configuración")
        if self.icon is not None:
            self.icon.stop()

    # -- configuración ----------------------------------------------------
    def _save(self) -> None:
        with self._lock:
            self.config = self.config.normalized()
            self.config.save()
        self.poller.update_config(self.config)

    def apply_device(self, address: str, device_type: str, name: str = "", encrypted: bool | None = None) -> None:
        """Guarda el equipo elegido y fuerza una lectura inmediata."""
        with self._lock:
            self.config = replace(
                self.config,
                address=normalize_address(address),
                device_type=(device_type or "AC180P").strip() or "AC180P",
                device_name=name or "",
                learned_encryption=encrypted,
                encryption="auto",
                first_run_done=True,
            )
            self.config.save()
        self.poller.update_config(self.config)
        self.poller.refresh_now()
        self._low_notified = False
        self._full_notified = False
        waiting = Status(
            online=False,
            error="conectando…",
            device_type=self.config.device_type,
            device_name=self.config.device_name or self.config.device_type,
        )
        self.store.update(waiting)
        self._apply_icon(waiting)
        _LOGGER.info("Equipo configurado: %s (%s, cifrado=%s)", address, device_type, encrypted)

    def _on_learned_encryption(self, encrypted: bool | None) -> None:
        with self._lock:
            if self.config.encryption != "auto":
                return
            if self.config.learned_encryption == encrypted:
                return
            self.config = replace(self.config, learned_encryption=encrypted)
            try:
                self.config.save()
            except OSError:
                _LOGGER.exception("No se pudo guardar el modo de cifrado")
        # Sin despertar el sondeo: la próxima lectura programada ya usará el dato.
        self.poller.update_config(self.config, wake=False)
        _LOGGER.info("Modo de cifrado recordado: %s", encrypted)

    def _on_address_changed(self, address: str) -> None:
        """El equipo cambió de dirección BLE (direcciones aleatorias): se guarda la nueva."""
        with self._lock:
            if self.config.address.upper() == address.upper():
                return
            self.config = replace(self.config, address=normalize_address(address))
            try:
                self.config.save()
            except OSError:
                _LOGGER.exception("No se pudo guardar la nueva dirección BLE")
        self.poller.update_config(self.config, wake=False)
        _LOGGER.info("Dirección BLE actualizada: %s", address)

    # -- acciones de usuario ---------------------------------------------
    def open_panel(self, _icon=None, _item=None) -> None:
        self.ui.open_panel()

    def open_device_dialog(self, _icon=None, _item=None) -> None:
        self.ui.open_device_dialog()

    def refresh_now(self, _icon=None, _item=None) -> None:
        self.poller.refresh_now()

    def _open_log(self, _icon=None, _item=None) -> None:
        try:
            os.startfile(str(log_path()))  # noqa: S606 - archivo propio
        except OSError:
            _LOGGER.exception("No se pudo abrir el registro")

    def _toggle_autostart(self, _icon=None, _item=None) -> None:
        try:
            autostart.set_enabled(not autostart.is_enabled())
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("No se pudo cambiar el inicio automático")
            self.ui.show_error("BLUETTI", f"No se pudo cambiar el inicio automático:\n{exc}")
        if self.icon is not None:
            self.icon.update_menu()

    def _metric_action(self, metric: str):
        def action(_icon, _item) -> None:
            with self._lock:
                self.config = replace(self.config, icon_metric=metric)
                self.config.save()
            self.poller.update_config(self.config, wake=False)
            self._apply_icon(self.store.snapshot())
            if self.icon is not None:
                self.icon.update_menu()

        return action

    def _metric_checked(self, metric: str):
        def checked(_item) -> bool:
            return self.config.icon_metric == metric

        return checked

    # -- icono ------------------------------------------------------------
    def _apply_icon(self, status: Status) -> None:
        icon = self.icon
        if icon is None:
            return
        try:
            icon.icon = render_icon(
                status,
                metric=self.config.icon_metric,
                size=ICON_SIZE,
                max_output_power=self.config.max_output_power,
            )
            icon.title = tooltip(
                status,
                fallback_name=self.config.device_name or self.config.device_type,
                poll_interval=self.config.poll_interval,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Error actualizando el icono")

    def _on_status(self, status: Status) -> None:
        if self._quitting:
            return
        self._apply_icon(status)
        if self.icon is not None:
            try:
                self.icon.update_menu()
            except Exception:  # noqa: BLE001
                pass
        self._maybe_notify(status)

    def _maybe_notify(self, status: Status) -> None:
        if self.icon is None or not self.config.notifications:
            return
        percent = status.battery_percent
        if not status.online or percent is None:
            return
        threshold = self.config.low_battery_threshold
        charging = status.mode in ("charging", "passthrough")
        if percent <= threshold and not charging and not self._low_notified:
            self._low_notified = True
            self.icon.notify(
                f"Batería baja: {percent}% · consumo {fmt_power(status.total_output_power)}",
                "BLUETTI",
            )
        elif percent > threshold + 5 or charging:
            self._low_notified = False
        if percent >= 100 and charging and not self._full_notified:
            self._full_notified = True
            self.icon.notify("Carga completa: 100 %", "BLUETTI")
        elif percent < 98:
            self._full_notified = False

    # -- menú -------------------------------------------------------------
    def _menu_summary(self, _item=None) -> str:
        status = self.store.snapshot()
        if status.online:
            return summary_line(status)
        return "Sin conexión · reintentando…"

    def _menu(self) -> Menu:
        return Menu(
            MenuItem(self._menu_summary, None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("Abrir panel", self.open_panel, default=True),
            MenuItem("Actualizar ahora", self.refresh_now),
            MenuItem(
                "Icono de la bandeja",
                Menu(
                    MenuItem(
                        ICON_METRICS["percent"],
                        self._metric_action("percent"),
                        checked=self._metric_checked("percent"),
                        radio=True,
                    ),
                    MenuItem(
                        ICON_METRICS["power"],
                        self._metric_action("power"),
                        checked=self._metric_checked("power"),
                        radio=True,
                    ),
                    MenuItem(
                        ICON_METRICS["both"],
                        self._metric_action("both"),
                        checked=self._metric_checked("both"),
                        radio=True,
                    ),
                ),
            ),
            MenuItem("Elegir dispositivo…", self.open_device_dialog),
            Menu.SEPARATOR,
            MenuItem(
                "Iniciar con Windows", self._toggle_autostart, checked=lambda _item: autostart.is_enabled()
            ),
            MenuItem("Ver registro", self._open_log),
            Menu.SEPARATOR,
            MenuItem("Salir", self.quit_app),
        )
