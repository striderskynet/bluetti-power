"""Interfaz gráfica (Tkinter) en un hilo propio: panel de estado y selector de equipo."""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import tkinter as tk
from tkinter import messagebox

from .ble import BluettiError, scan_devices
from .config import is_valid_address, normalize_address
from .status import (
    MODE_CHARGING,
    MODE_PASSTHROUGH,
    band,
    fmt_age,
    fmt_percent,
    fmt_power,
    fmt_power_compact,
    state_label,
)

_LOGGER = logging.getLogger(__name__)

BG = "#0b1220"
CARD = "#152238"
TEXT = "#e6edf7"
MUTED = "#94a3b8"
BORDER = "#29405c"
ACCENT = "#38bdf8"
GREEN = "#4ade80"
YELLOW = "#facc15"
RED = "#f87171"
CYAN = "#38bdf8"
PANEL_BG = "#0f172a"

BAND_COLORS = {"good": GREEN, "warn": YELLOW, "bad": RED, "unknown": MUTED}


def apply_window_icon(window: tk.Toplevel) -> None:
    """Pone el icono de la aplicación a una ventana (si el .ico está disponible)."""
    try:
        from .paths import resource_path

        path = resource_path("assets/bluetti.ico")
        if path.exists():
            window.iconbitmap(default=str(path))
    except Exception:  # noqa: BLE001 - el icono es cosmético
        pass


def _button(master: tk.Misc, text: str, command) -> tk.Button:
    return tk.Button(
        master,
        text=text,
        command=command,
        bg=BORDER,
        fg=TEXT,
        activebackground=ACCENT,
        activeforeground=BG,
        relief="flat",
        bd=0,
        padx=10,
        pady=4,
        cursor="hand2",
        font=("Segoe UI", 8),
    )


class UiThread:
    """Hilo dedicado a Tk: recibe órdenes por una cola y muestra ventanas."""

    def __init__(self, app) -> None:
        self.app = app
        self._queue: queue.Queue = queue.Queue()
        self._root: tk.Tk | None = None
        self._thread: threading.Thread | None = None
        self._panel: StatusPanel | None = None
        self._dialog: DeviceDialog | None = None

    # -- API desde cualquier hilo ----------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="bluetti-ui", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.post("quit")

    def post(self, kind: str, payload=None) -> None:
        self._queue.put((kind, payload))

    def open_panel(self) -> None:
        self.post("panel")

    def open_device_dialog(self) -> None:
        self.post("dialog")

    def show_error(self, title: str, message: str) -> None:
        self.post("error", (title, message))

    # -- hilo Tk ----------------------------------------------------------
    def _run(self) -> None:
        root = tk.Tk()
        root.withdraw()
        self._root = root
        root.after(60, self._drain)
        try:
            root.mainloop()
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                self._dispatch(kind, payload)
        except queue.Empty:
            pass
        except Exception:  # noqa: BLE001 - la UI nunca debe morir
            _LOGGER.exception("Error procesando evento de interfaz")
        if self._root is not None:
            try:
                self._root.after(60, self._drain)
            except tk.TclError:
                pass

    def _dispatch(self, kind: str, payload) -> None:
        if kind == "quit":
            if self._root is not None:
                self._root.quit()
        elif kind == "panel":
            self._show_panel()
        elif kind == "dialog":
            self._show_dialog()
        elif kind == "error":
            title, message = payload
            messagebox.showerror(title, message)
        elif kind == "devices":
            if self._dialog is not None and self._dialog.alive():
                self._dialog.set_devices(payload)
        elif kind == "devices_error":
            if self._dialog is not None and self._dialog.alive():
                self._dialog.set_error(str(payload))
        elif kind == "panel_closed":
            self._panel = None
        elif kind == "dialog_closed":
            self._dialog = None

    def _show_panel(self) -> None:
        if self._panel is not None and self._panel.alive():
            self._panel.lift()
            return
        self._panel = StatusPanel(self.app, self._root, on_close=lambda: self.post("panel_closed"))

    def _show_dialog(self) -> None:
        if self._dialog is not None and self._dialog.alive():
            self._dialog.lift()
            return
        self._dialog = DeviceDialog(self.app, self._root, on_close=lambda: self.post("dialog_closed"))


class StatusPanel:
    """Ventana con el detalle del estado."""

    def __init__(self, app, master: tk.Tk, on_close) -> None:
        self.app = app
        self.on_close = on_close
        self.win = tk.Toplevel(master)
        self.win.withdraw()
        self.win.title("BLUETTI — estado")
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", lambda _event: self.close())
        self._tick_id: str | None = None
        apply_window_icon(self.win)
        self._build()
        self._place()
        self.win.deiconify()
        self.win.lift()
        self._tick()

    # -- construcción -----------------------------------------------------
    def _build(self) -> None:
        outer = tk.Frame(self.win, bg=BG, padx=16, pady=12)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x")
        self.lbl_device = tk.Label(header, text="BLUETTI", bg=BG, fg=TEXT, font=("Segoe UI", 11, "bold"))
        self.lbl_device.pack(side="left")
        self.dot = tk.Canvas(header, width=10, height=10, bg=BG, highlightthickness=0)
        self.dot.pack(side="left", padx=(10, 4))
        self.lbl_state = tk.Label(header, text="Conectando…", bg=BG, fg=MUTED, font=("Segoe UI", 9))
        self.lbl_state.pack(side="left")

        battery = tk.Frame(outer, bg=CARD, padx=12, pady=8)
        battery.pack(fill="x", pady=(10, 0))
        self.lbl_pct = tk.Label(battery, text="—", bg=CARD, fg=MUTED, font=("Segoe UI", 34, "bold"))
        self.lbl_pct.pack(side="left")
        tk.Label(battery, text="%", bg=CARD, fg=MUTED, font=("Segoe UI", 12)).pack(side="left", padx=(0, 8), pady=(14, 0))
        self.lbl_mode = tk.Label(battery, text="BATERÍA", bg=CARD, fg=MUTED, font=("Segoe UI", 8))
        self.lbl_mode.pack(side="right", pady=(16, 0))

        consumption = tk.Frame(outer, bg=CARD, padx=12, pady=8)
        consumption.pack(fill="x", pady=(6, 0))
        self.lbl_w = tk.Label(consumption, text="—", bg=CARD, fg=TEXT, font=("Segoe UI", 24, "bold"))
        self.lbl_w.pack(side="left")
        tk.Label(consumption, text="W", bg=CARD, fg=MUTED, font=("Segoe UI", 11)).pack(side="left", padx=(2, 10), pady=(8, 0))
        right = tk.Frame(consumption, bg=CARD)
        right.pack(side="right")
        tk.Label(right, text="CONSUMO ACTUAL", bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="e")
        self.lbl_breakdown = tk.Label(right, text="AC — · DC —", bg=CARD, fg=MUTED, font=("Segoe UI", 8))
        self.lbl_breakdown.pack(anchor="e")

        self.lbl_input = tk.Label(outer, text="Entrada: —", bg=BG, fg=MUTED, font=("Segoe UI", 9))
        self.lbl_input.pack(anchor="w", pady=(8, 0))

        self.spark = tk.Canvas(outer, width=328, height=54, bg=CARD, highlightthickness=0)
        self.spark.pack(fill="x", pady=(6, 0))

        footer = tk.Frame(outer, bg=BG)
        footer.pack(fill="x", pady=(8, 0))
        self.lbl_updated = tk.Label(footer, text="", bg=BG, fg=MUTED, font=("Segoe UI", 8))
        self.lbl_updated.pack(side="left")
        _button(footer, "Salir", self.app.quit_app).pack(side="right", padx=(6, 0))
        _button(footer, "Dispositivo…", self.app.open_device_dialog).pack(side="right", padx=(6, 0))
        _button(footer, "Actualizar", self.app.refresh_now).pack(side="right")

    def _place(self) -> None:
        self.win.update_idletasks()
        width = self.win.winfo_reqwidth()
        height = self.win.winfo_reqheight()
        screen_w = self.win.winfo_screenwidth()
        screen_h = self.win.winfo_screenheight()
        x = max(8, screen_w - width - 24)
        y = max(8, screen_h - height - 90)
        self.win.geometry(f"+{x}+{y}")

    # -- ciclo de vida ----------------------------------------------------
    def alive(self) -> bool:
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def lift(self) -> None:
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def close(self) -> None:
        if self._tick_id is not None:
            try:
                self.win.after_cancel(self._tick_id)
            except tk.TclError:
                pass
            self._tick_id = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.on_close()

    # -- actualización ----------------------------------------------------
    def _tick(self) -> None:
        if not self.alive():
            return
        try:
            self._update(self.app.store.snapshot())
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Error actualizando el panel")
        try:
            self._tick_id = self.win.after(1000, self._tick)
        except tk.TclError:
            pass

    def _update(self, status) -> None:
        online = status.online
        percent = status.battery_percent
        color = BAND_COLORS[band(percent)] if online else MUTED

        self.lbl_device.config(text=(status.device_type or status.device_name or "BLUETTI"))
        self.win.title(f"BLUETTI — {fmt_percent(percent)}" if online else "BLUETTI — sin conexión")
        self.lbl_pct.config(text=str(percent) if percent is not None else "—", fg=color)
        self.lbl_mode.config(
            text="BATERÍA" if online else "ÚLTIMA LECTURA",
        )

        state_color = MUTED
        if online:
            state_text = state_label(status)
            if status.mode == MODE_CHARGING:
                state_color = CYAN
            elif status.mode == MODE_PASSTHROUGH:
                state_color = CYAN
            else:
                state_color = GREEN
        else:
            state_text = status.error or "Sin conexión"
        self.dot.delete("all")
        self.dot.create_oval(1, 1, 9, 9, fill=state_color, outline="")
        self.lbl_state.config(text=state_text, fg=state_color)

        output = status.total_output_power
        self.lbl_w.config(text=fmt_power_compact(output) if output is not None else "—")
        self.lbl_breakdown.config(
            text=f"AC {fmt_power(status.ac_output_power)} · DC {fmt_power(status.dc_output_power)}"
        )
        self.lbl_input.config(
            text=(
                f"Entrada: {fmt_power(status.total_input_power)}"
                f"  (AC {fmt_power(status.ac_input_power)} · solar {fmt_power(status.dc_input_power)})"
            )
        )
        if online:
            self.lbl_updated.config(text=f"Actualizado {fmt_age(status.age())}")
        else:
            self.lbl_updated.config(text=f"Reintentando · {fmt_age(status.age())}")
        self._draw_sparkline()

    def _draw_sparkline(self) -> None:
        canvas = self.spark
        canvas.delete("all")
        history = self.app.store.history()
        width = int(canvas.winfo_width() or 0)
        height = int(canvas.winfo_height() or 0)
        if width < 100:
            width = 328
        if height < 30:
            height = 54
        if len(history) < 3:
            canvas.create_text(
                width / 2, height / 2, text="Recopilando historial de consumo…", fill=MUTED, font=("Segoe UI", 8)
            )
            return

        points = history[-120:]
        values = [(w or 0) for _ts, _pct, w in points]
        maximum = max(200, max(values))
        pad = 4
        usable_w = max(1, width - pad * 2)
        usable_h = max(1, height - pad * 2)
        coords: list[float] = []
        for index, value in enumerate(values):
            x = pad + usable_w * index / max(1, len(values) - 1)
            y = pad + usable_h - usable_h * (value / maximum)
            coords.extend((x, y))
        polygon = [pad, height - pad] + coords + [pad + usable_w, height - pad]
        canvas.create_polygon(polygon, fill="#134e4a", outline="")
        canvas.create_line(coords, fill=GREEN, width=1.5, smooth=True)
        canvas.create_text(
            pad,
            2,
            text=f"Consumo · máx {maximum} W",
            fill=MUTED,
            font=("Segoe UI", 7),
            anchor="nw",
        )


class DeviceDialog:
    """Selector de equipo: escanea, lista dispositivos BLUETTI y guarda el elegido."""

    def __init__(self, app, master: tk.Tk, on_close) -> None:
        self.app = app
        self.on_close = on_close
        self.devices = []
        self._scanning = False

        self.win = tk.Toplevel(master)
        self.win.withdraw()
        self.win.title("Elegir dispositivo BLUETTI")
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", lambda _event: self.close())
        apply_window_icon(self.win)

        frame = tk.Frame(self.win, bg=BG, padx=16, pady=12)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text=(
                "Enciende el AC180P y mantén el Bluetooth activo.\n"
                "Windows debe poder verlo (sin emparejar).\n"
                "Al elegirlo, el icono aparecerá en la bandeja del sistema (puede que\n"
                "quede en el menú ^ y tengas que arrastrarlo a la barra)."
            ),
            bg=BG,
            fg=MUTED,
            justify="left",
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        self.lbl_status = tk.Label(frame, text="Buscando dispositivos…", bg=BG, fg=ACCENT, font=("Segoe UI", 9))
        self.lbl_status.pack(anchor="w", pady=(8, 4))

        list_frame = tk.Frame(frame, bg=CARD)
        list_frame.pack(fill="both", expand=True)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        self.listbox = tk.Listbox(
            list_frame,
            height=7,
            width=62,
            bg=CARD,
            fg=TEXT,
            selectbackground=ACCENT,
            selectforeground=BG,
            highlightthickness=0,
            bd=0,
            relief="flat",
            font=("Consolas", 9),
            yscrollcommand=scrollbar.set,
        )
        self.listbox.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        scrollbar.config(command=self.listbox.yview)
        self.listbox.bind("<Double-Button-1>", lambda _event: self._use_selected())
        self.listbox.bind("<<ListboxSelect>>", lambda _event: self._update_details())

        self.lbl_details = tk.Label(frame, text="", bg=BG, fg=MUTED, font=("Segoe UI", 8))
        self.lbl_details.pack(anchor="w", pady=(2, 0))

        buttons = tk.Frame(frame, bg=BG)
        buttons.pack(fill="x", pady=(8, 0))
        _button(buttons, "Escanear de nuevo", self.scan).pack(side="left")
        _button(buttons, "Usar seleccionado", self._use_selected).pack(side="left", padx=(6, 0))
        _button(buttons, "Cerrar", self.close).pack(side="right")

        manual = tk.Frame(frame, bg=BG)
        manual.pack(fill="x", pady=(10, 0))
        tk.Label(manual, text="¿No aparece? Escribe su dirección Bluetooth:", bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(
            anchor="w"
        )
        row = tk.Frame(manual, bg=BG)
        row.pack(fill="x", pady=(2, 0))
        self.entry_mac = tk.Entry(
            row,
            width=22,
            bg=CARD,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            font=("Consolas", 10),
        )
        self.entry_mac.pack(side="left", fill="x", expand=True, ipady=4)
        _button(row, "Usar dirección", self._use_manual).pack(side="left", padx=(6, 0))

        self._place()
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()
        self.scan()

    def _place(self) -> None:
        self.win.update_idletasks()
        width = self.win.winfo_reqwidth()
        height = self.win.winfo_reqheight()
        screen_w = self.win.winfo_screenwidth()
        screen_h = self.win.winfo_screenheight()
        self.win.geometry(f"+{max(8, (screen_w - width) // 2)}+{max(8, (screen_h - height) // 2)}")

    # -- escaneo ----------------------------------------------------------
    def scan(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        self.lbl_status.config(text="Escaneando Bluetooth (8 s)…", fg=ACCENT)
        self.listbox.delete(0, "end")
        self.devices = []

        def job() -> None:
            try:
                devices = asyncio.run(scan_devices(8.0))
                self.app.ui.post("devices", devices)
            except BluettiError as exc:
                self.app.ui.post("devices_error", str(exc))
            except Exception as exc:  # noqa: BLE001
                self.app.ui.post("devices_error", f"error inesperado: {exc}")
            finally:
                self._scanning = False

        threading.Thread(target=job, name="bluetti-scan", daemon=True).start()

    def set_devices(self, devices) -> None:
        self._scanning = False
        self.devices = [d for d in devices if d.device_type and d.device_type in self.app.supported_types]
        self.listbox.delete(0, "end")
        for device in self.devices:
            if device.encrypted is True:
                secure = "cifrado"
            elif device.encrypted is False:
                secure = "sin cifrar"
            else:
                secure = "por detectar"
            rssi = f"{device.rssi:>4} dBm" if device.rssi is not None else "      ?  "
            self.listbox.insert("end", f"{device.name or '(sin nombre)':<22} {rssi}  {secure}")
        if self.devices:
            self.lbl_status.config(
                text=f"{len(self.devices)} equipo(s) BLUETTI encontrado(s). Selecciona uno.",
                fg=GREEN,
            )
            self.listbox.selection_set(0)
            self._update_details()
        else:
            self.lbl_status.config(
                text="No se encontró ningún BLUETTI. Acércalo, enciéndelo y vuelve a escanear.",
                fg=YELLOW,
            )
            self.lbl_details.config(text="")

    def _update_details(self) -> None:
        selection = self.listbox.curselection()
        if not selection or selection[0] >= len(self.devices):
            self.lbl_details.config(text="")
            return
        device = self.devices[selection[0]]
        if device.encrypted is True:
            secure = "canal cifrado"
        elif device.encrypted is False:
            secure = "canal sin cifrar"
        else:
            secure = "cifrado se detectará al conectar"
        self.lbl_details.config(
            text=f"Dirección {device.address} · modelo {device.device_type} · {secure}"
        )

    def set_error(self, message: str) -> None:
        self._scanning = False
        self.lbl_status.config(text=f"Error: {message}", fg=RED)
        self.lbl_details.config(text="")

    # -- acciones ---------------------------------------------------------
    def _use_selected(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showinfo("BLUETTI", "Selecciona un dispositivo de la lista.", parent=self.win)
            return
        device = self.devices[selection[0]]
        self.app.apply_device(
            address=device.address,
            device_type=device.device_type or "AC180P",
            name=device.name,
            encrypted=device.encrypted,
        )
        self.close()

    def _use_manual(self) -> None:
        address = normalize_address(self.entry_mac.get())
        if not is_valid_address(address):
            messagebox.showwarning(
                "BLUETTI",
                "Escribe la dirección Bluetooth con el formato AA:BB:CC:DD:EE:FF.",
                parent=self.win,
            )
            return
        self.app.apply_device(
            address=address,
            device_type="AC180P",
            name=self.entry_mac.get().strip(),
            encrypted=None,
        )
        self.close()

    def alive(self) -> bool:
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def lift(self) -> None:
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def close(self) -> None:
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.on_close()
