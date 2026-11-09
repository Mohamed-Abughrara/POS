from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from ...application.dto import BackupInfo
from ...application.errors import BackupError
from .migrations import MIGRATIONS


class SqliteBackupService:
    def __init__(self, conn: sqlite3.Connection, backup_dir: Path, keep: int = 30):
        self._conn = conn
        self._dir = Path(backup_dir)
        self._keep = keep

    def create(self, destination: Optional[Path] = None) -> BackupInfo:
        self._dir.mkdir(parents=True, exist_ok=True)
        dest = Path(destination) if destination else self._dir / f"souqpos-{datetime.now():%Y%m%d-%H%M%S}.db"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            raise BackupError(f"{dest} already exists")
        target = sqlite3.connect(str(dest))
        try:
            self._conn.backup(target)       # consistent snapshot even in WAL mode
        finally:
            target.close()
        self._prune()
        return BackupInfo(str(dest), dest.stat().st_size, datetime.now())

    def list(self) -> list[BackupInfo]:
        if not self._dir.exists():
            return []
        files = sorted(self._dir.glob("souqpos-*.db"), reverse=True)
        return [BackupInfo(str(f), f.stat().st_size, datetime.fromtimestamp(f.stat().st_mtime)) for f in files]

    def restore(self, source: Path) -> None:
        source = Path(source)
        if not source.is_file():
            raise BackupError(f"{source} not found")
        src = sqlite3.connect(str(source))
        try:
            ok = src.execute("PRAGMA integrity_check").fetchone()[0]
            version = src.execute("PRAGMA user_version").fetchone()[0]
            if ok != "ok" or not 1 <= version <= len(MIGRATIONS):
                raise BackupError("not a valid SouqPOS backup")
            if self._conn.in_transaction:
                raise BackupError("a transaction is in progress")
            self._conn.execute("PRAGMA foreign_keys = OFF")
            try:
                src.backup(self._conn)
            finally:
                self._conn.execute("PRAGMA foreign_keys = ON")
        except sqlite3.DatabaseError as exc:
            raise BackupError(str(exc)) from exc
        finally:
            src.close()

    def _prune(self) -> None:
        for old in sorted(self._dir.glob("souqpos-*.db"), reverse=True)[self._keep:]:
            try:
                old.unlink()
            except OSError:
                pass
