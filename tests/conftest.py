from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pos.application.dto import ProductView, UserInput                       # noqa: E402
from pos.application.use_cases.admin import AdminUseCases, SeedDefaults      # noqa: E402
from pos.application.use_cases.auth import AuthUseCases                      # noqa: E402
from pos.application.use_cases.catalogue import CatalogueUseCases            # noqa: E402
from pos.application.use_cases.checkout import CheckoutUseCases              # noqa: E402
from pos.application.use_cases.refunds import RefundUseCases                 # noqa: E402
from pos.application.use_cases.reports import ReportUseCases                 # noqa: E402
from pos.application.use_cases.shifts import ShiftUseCases                   # noqa: E402
from pos.domain.barcode import check_digit                                   # noqa: E402
from pos.infrastructure.csv_export import CsvFileExporter                    # noqa: E402
from pos.infrastructure.printing.printers import NullPrinter                 # noqa: E402
from pos.infrastructure.security.hasher import Pbkdf2Hasher                  # noqa: E402
from pos.infrastructure.sqlite.backup import SqliteBackupService             # noqa: E402
from pos.infrastructure.sqlite.connection import connect                     # noqa: E402
from pos.infrastructure.sqlite.queries import SqliteReportQueries            # noqa: E402
from pos.infrastructure.sqlite.uow import uow_factory                        # noqa: E402
from pos.infrastructure.system import UuidGenerator                          # noqa: E402


def ean13(body12: str) -> str:
    return body12 + str(check_digit(body12))


class FakeClock:
    def __init__(self):
        self.t = datetime(2026, 11, 9, 9, 0, 0)

    def now(self):
        self.t += timedelta(seconds=1)
        return self.t


@dataclass
class App:
    conn: object
    clock: FakeClock
    printer: NullPrinter
    hasher: Pbkdf2Hasher
    auth: AuthUseCases
    checkout: CheckoutUseCases
    refunds: RefundUseCases
    shifts: ShiftUseCases
    catalogue: CatalogueUseCases
    reports: ReportUseCases
    admin: AdminUseCases
    uow: object
    admin_id: str = ""
    manager_id: str = ""
    cashier_id: str = ""
    cola: str = ""       # barcode of a 1.500 LYD, 15% exclusive-tax... see conftest
    rice: str = ""


def build_app(tmp_path: Path, db: str = ":memory:") -> App:
    conn = connect(db)
    clock, ids, printer = FakeClock(), UuidGenerator(), NullPrinter()
    hasher = Pbkdf2Hasher(iterations=1000)
    uow = uow_factory(conn)
    queries = SqliteReportQueries(conn)
    app = App(
        conn=conn, clock=clock, printer=printer, hasher=hasher,
        auth=AuthUseCases(uow, clock, ids, hasher),
        checkout=CheckoutUseCases(uow, clock, ids, hasher, printer),
        refunds=RefundUseCases(uow, clock, ids, hasher, printer),
        shifts=ShiftUseCases(uow, clock, ids, hasher, printer, queries),
        catalogue=CatalogueUseCases(uow, clock, ids),
        reports=ReportUseCases(uow, clock, ids, queries, CsvFileExporter()),
        admin=AdminUseCases(uow, clock, ids, hasher, SqliteBackupService(conn, tmp_path / "backups")),
        uow=uow)
    SeedDefaults(uow, clock, ids, hasher).run("admin", "admin123")
    admin = app.auth.login("admin", "admin123")
    app.admin_id = admin.id
    app.manager_id = app.admin.save_user(admin.id, UserInput(None, "manager", "Manager", "MANAGER", password="manager1", pin="4321")).id
    app.cashier_id = app.admin.save_user(admin.id, UserInput(None, "cashier", "Cashier", "CASHIER", password="cashier1", pin="1234")).id
    cat = app.catalogue.list_categories(admin.id)[0]
    from pos.application.dto import CategoryView
    taxed = app.catalogue.save_category(admin.id, CategoryView(None, "مواد", "Taxed", 500, False))
    app.cola = ean13("622000000001")
    app.rice = ean13("622000000002")
    app.catalogue.save_product(admin.id, ProductView(None, "COLA", app.cola, "كولا", "Cola", cat.id, 1500, 900, "PIECE", Decimal(5)))
    app.catalogue.save_product(admin.id, ProductView(None, "RICE", app.rice, "أرز", "Rice", taxed.id, 2500, 1500, "KG", Decimal(2)))
    for sku in ("COLA", "RICE"):
        pid = next(p.id for p in app.catalogue.search_products(admin.id, sku))
        from pos.application.dto import AdjustStockInput
        app.catalogue.adjust_stock(AdjustStockInput(app.manager_id, pid, "RECEIPT", Decimal(100), "initial"))
    return app


@pytest.fixture
def app(tmp_path):
    return build_app(tmp_path)
