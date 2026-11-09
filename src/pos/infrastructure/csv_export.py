from __future__ import annotations

import csv
from pathlib import Path
from typing import Sequence


class CsvFileExporter:
    """Writes a report as UTF-8 (with BOM so Excel reads Arabic) CSV. Money stays in dirhams."""

    def write(self, path: Path, columns: Sequence[str], rows: Sequence[Sequence], totals: Sequence) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(columns)
            w.writerows(rows)
            if totals:
                w.writerow(totals)
