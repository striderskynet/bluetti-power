"""Carga y guardado de la configuración (JSON en %LOCALAPPDATA%)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, fields, replace
from pathlib import Path

from .paths import config_path

_LOGGER = logging.getLogger(__name__)

ICON_METRICS = ("percent", "power")
ENCRYPTION_MODES = ("auto", "on", "off")
_ADDRESS_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$", re.IGNORECASE)


def normalize_address(value: str) -> str:
    cleaned = (value or "").strip().upper().replace("-", ":")
    if not cleaned:
        return ""
    if _ADDRESS_RE.match(cleaned):
        return cleaned
    return cleaned


def is_valid_address(value: str) -> bool:
    return bool(_ADDRESS_RE.match((value or "").strip().upper().replace("-", ":")))


@dataclass
class Config:
    """Configuración persistente de la aplicación."""

    address: str = ""
    device_name: str = ""
    device_type: str = "AC180P"
    encryption: str = "auto"
    learned_encryption: bool | None = None
    poll_interval: int = 60
    icon_metric: str = "percent"
    max_output_power: int = 1800
    low_battery_threshold: int = 20
    notifications: bool = True
    demo: bool = False
    log_level: str = "INFO"
    first_run_done: bool = False

    def normalized(self) -> "Config":
        cfg = replace(self)
        cfg.address = normalize_address(cfg.address)
        cfg.device_type = (cfg.device_type or "AC180P").strip() or "AC180P"
        if cfg.icon_metric not in ICON_METRICS:
            cfg.icon_metric = "percent"
        if cfg.encryption not in ENCRYPTION_MODES:
            cfg.encryption = "auto"
        cfg.poll_interval = max(10, min(int(cfg.poll_interval or 30), 600))
        cfg.max_output_power = max(100, int(cfg.max_output_power or 1800))
        cfg.low_battery_threshold = max(5, min(int(cfg.low_battery_threshold or 20), 60))
        cfg.log_level = (cfg.log_level or "INFO").upper()
        return cfg

    def save(self, path: Path | None = None) -> None:
        target = path or config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".tmp")
        data = {f.name: getattr(self, f.name) for f in fields(self)}
        data["demo"] = False  # el modo demo es solo de la sesión, no se persiste
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temp.replace(target)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        target = path or config_path()
        if not target.exists():
            return cls()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _LOGGER.warning("No se pudo leer %s (%s); usando valores por defecto", target, exc)
            return cls()
        if not isinstance(raw, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        cfg = cls(**{k: v for k, v in raw.items() if k in known})
        return cfg.normalized()
