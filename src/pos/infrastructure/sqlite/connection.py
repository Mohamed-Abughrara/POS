from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

from .migrations import migrate


def connect(path: Union[str, Path]) -> sqlite3.Connection:
    """Open the database (WAL, FK on, synchronous=NORMAL) and apply pending migrations.

    isolation_level=None gives autocommit; the Unit of Work issues explicit BEGIN/COMMIT.
    """
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    migrate(conn)
    return conn
