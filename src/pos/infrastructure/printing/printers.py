from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..config.settings import PrinterConfig
from .render import render_document

log = logging.getLogger(__name__)


class NullPrinter:
    """Collects documents in memory (tests) or fails on demand to exercise NFR-05."""

    def __init__(self, fail: bool = False):
        self.documents: list[Any] = []
        self.drawer_kicks = 0
        self.fail = fail

    def print(self, document: Any) -> None:
        if self.fail:
            raise IOError("printer offline")
        self.documents.append(document)

    def open_drawer(self) -> None:
        if self.fail:
            raise IOError("printer offline")
        self.drawer_kicks += 1


class FilePrinter:
    """Writes each document as a UTF-8 .txt file (also a PDF-free fallback when no printer is attached)."""

    def __init__(self, directory: Path, width: int = 42):
        self._dir = Path(directory)
        self._width = width

    def print(self, document: Any) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        kind = type(document).__name__.lower()
        path = self._dir / f"{datetime.now():%Y%m%d-%H%M%S-%f}-{kind}.txt"
        path.write_text(render_document(document, self._width), encoding="utf-8")
        log.info("document written to %s", path)

    def open_drawer(self) -> None:
        log.info("cash drawer kick (file backend: no hardware)")


class EscPosPrinter:
    """ESC/POS over USB or network using python-escpos (optional dependency)."""

    def __init__(self, connect: Callable[[], Any], width: int = 42):
        self._connect = connect
        self._width = width

    def print(self, document: Any) -> None:
        text = render_document(document, self._width)
        dev = self._connect()
        try:
            try:
                dev.charcode("CP864")
                data = text.encode("cp864", errors="replace")
            except Exception:  # printer without Arabic code page support
                data = text.encode("ascii", errors="replace")
            dev._raw(data)
            dev.cut()
        finally:
            dev.close()

    def open_drawer(self) -> None:
        dev = self._connect()
        try:
            dev.cashdraw(2)
        finally:
            dev.close()


def build_printer(cfg: PrinterConfig, receipts_dir: Path):
    backend = cfg.backend.lower()
    if backend == "null":
        return NullPrinter()
    if backend in ("usb", "network"):
        try:
            from escpos.printer import Network, Usb  # type: ignore
        except ImportError:
            log.warning("python-escpos is not installed; falling back to the file printer")
            return FilePrinter(receipts_dir, cfg.width)
        if backend == "usb":
            return EscPosPrinter(lambda: Usb(cfg.usb_vendor_id, cfg.usb_product_id), cfg.width)
        return EscPosPrinter(lambda: Network(cfg.network_host, cfg.network_port), cfg.width)
    return FilePrinter(receipts_dir, cfg.width)
