"""TOML configuration (tomllib). A default file is written on first run."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TOML = """\
# SouqPOS configuration
data_dir = ""                 # empty = per-user data folder
default_locale = "en"         # "en" or "ar"
backup_interval_hours = 12    # scheduled backups while the app is open (0 = off)
backups_to_keep = 30

[printer]
backend = "file"              # file | usb | network | null
receipts_dir = ""             # file backend: where receipt .txt files go (empty = <data_dir>/receipts)
width = 42                    # characters per line
usb_vendor_id = 0             # usb backend (e.g. 0x04b8 as 1208)
usb_product_id = 0
network_host = ""             # network backend
network_port = 9100
"""


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "SouqPOS"


@dataclass
class PrinterConfig:
    backend: str = "file"
    receipts_dir: str = ""
    width: int = 42
    usb_vendor_id: int = 0
    usb_product_id: int = 0
    network_host: str = ""
    network_port: int = 9100


@dataclass
class AppConfig:
    data_dir: Path
    default_locale: str = "en"
    backup_interval_hours: float = 12
    backups_to_keep: int = 30
    printer: PrinterConfig = field(default_factory=PrinterConfig)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "souqpos.db"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "logs" / "souqpos.log"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def receipts_dir(self) -> Path:
        return Path(self.printer.receipts_dir) if self.printer.receipts_dir else self.data_dir / "receipts"


def load_config(path: Path | None = None, data_dir_override: Path | None = None) -> AppConfig:
    data_dir = data_dir_override or default_data_dir()
    cfg_path = path or data_dir / "config.toml"
    if not cfg_path.exists():
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(DEFAULT_TOML, encoding="utf-8")
    raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    printer_raw = raw.get("printer", {})
    printer = PrinterConfig(**{k: v for k, v in printer_raw.items() if k in PrinterConfig.__dataclass_fields__})
    return AppConfig(
        data_dir=data_dir_override or (Path(raw["data_dir"]) if raw.get("data_dir") else data_dir),
        default_locale=raw.get("default_locale", "en"),
        backup_interval_hours=float(raw.get("backup_interval_hours", 12)),
        backups_to_keep=int(raw.get("backups_to_keep", 30)),
        printer=printer)
