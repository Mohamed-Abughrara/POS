"""UC-13 GenerateReport / ExportCsv."""
from __future__ import annotations

from pathlib import Path

from ..dto import ReportInput, ReportView
from ..errors import InvalidDateRange, InvalidInput
from ..permissions import Permission
from ..ports import CsvExporter, ReportQueries
from .common import UowFactory, UseCase

KINDS = ("DAILY", "BY_PRODUCT", "BY_CASHIER", "BY_PAYMENT", "TAX")


class ReportUseCases(UseCase):
    def __init__(self, uow_factory: UowFactory, clock, ids, queries: ReportQueries, exporter: CsvExporter):
        super().__init__(uow_factory, clock, ids)
        self._queries = queries
        self._exporter = exporter

    def generate(self, inp: ReportInput) -> ReportView:
        with self._uow_factory() as uow:
            self._user(uow, inp.actor_id, Permission.REPORTS)
        if inp.kind not in KINDS:
            raise InvalidInput(f"unknown report {inp.kind}")
        if inp.date_from > inp.date_to:
            raise InvalidDateRange(f"{inp.date_from} > {inp.date_to}")
        columns, rows, totals = self._queries.run(inp.kind, inp.date_from, inp.date_to, inp.cashier_id)
        return ReportView(inp.kind, columns, rows, totals)

    def export_csv(self, inp: ReportInput, path: Path) -> Path:
        view = self.generate(inp)
        self._exporter.write(path, view.columns, view.rows, view.totals)
        return path
