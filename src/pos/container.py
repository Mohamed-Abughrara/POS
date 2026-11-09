"""Composition root helpers: the only module (with main.py) that knows every concrete class (PDR 5.7).

Kept inside the package so tests can build the same graph. Import-linter allows it to import everything.
"""
from __future__ import annotations

import logging
import logging.handlers
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .adapters.controllers import (AdminController, AuthController, CatalogueController, CheckoutController,
                                   RefundController, ReportController, Session, ShiftController)
from .application.use_cases.admin import AdminUseCases, SeedDefaults
from .application.use_cases.auth import AuthUseCases
from .application.use_cases.catalogue import CatalogueUseCases
from .application.use_cases.checkout import CheckoutUseCases
from .application.use_cases.refunds import RefundUseCases
from .application.use_cases.reports import ReportUseCases
from .application.use_cases.shifts import ShiftUseCases
from .infrastructure.config.settings import AppConfig, load_config
from .infrastructure.csv_export import CsvFileExporter
from .infrastructure.i18n.translator import translator_factory
from .infrastructure.printing.printers import build_printer
from .infrastructure.security.hasher import Pbkdf2Hasher
from .infrastructure.sqlite.backup import SqliteBackupService
from .infrastructure.sqlite.connection import connect
from .infrastructure.sqlite.queries import SqliteReportQueries
from .infrastructure.sqlite.uow import uow_factory
from .infrastructure.system import SystemClock, UuidGenerator


@dataclass
class Container:
    config: AppConfig
    conn: object
    session: Session
    auth: AuthController
    checkout: CheckoutController
    refund: RefundController
    shift: ShiftController
    catalogue: CatalogueController
    report: ReportController
    admin: AdminController
    admin_uc: AdminUseCases
    catalogue_uc: CatalogueUseCases
    auth_uc: AuthUseCases
    seeded: bool = False


def configure_logging(config: AppConfig) -> None:
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(config.log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def build(config: AppConfig, printer=None, hasher: Optional[Pbkdf2Hasher] = None) -> Container:
    conn = connect(config.db_path)
    clock, ids = SystemClock(), UuidGenerator()
    hasher = hasher or Pbkdf2Hasher()
    printer = printer or build_printer(config.printer, config.receipts_dir)
    uow = uow_factory(conn)
    queries = SqliteReportQueries(conn)
    backup = SqliteBackupService(conn, config.backup_dir, config.backups_to_keep)

    auth_uc = AuthUseCases(uow, clock, ids, hasher)
    admin_uc = AdminUseCases(uow, clock, ids, hasher, backup)
    catalogue_uc = CatalogueUseCases(uow, clock, ids)
    checkout_uc = CheckoutUseCases(uow, clock, ids, hasher, printer)
    refund_uc = RefundUseCases(uow, clock, ids, hasher, printer)
    shift_uc = ShiftUseCases(uow, clock, ids, hasher, printer, queries)
    report_uc = ReportUseCases(uow, clock, ids, queries, CsvFileExporter())
    seeded = SeedDefaults(uow, clock, ids, hasher).run()

    session = Session(translator_factory, config.default_locale)
    return Container(
        config=config, conn=conn, session=session,
        auth=AuthController(session, auth_uc, admin_uc), checkout=CheckoutController(session, checkout_uc, catalogue_uc),
        refund=RefundController(session, refund_uc), shift=ShiftController(session, shift_uc),
        catalogue=CatalogueController(session, catalogue_uc),
        report=ReportController(session, report_uc, config.exports_dir), admin=AdminController(session, admin_uc),
        admin_uc=admin_uc, catalogue_uc=catalogue_uc, auth_uc=auth_uc, seeded=seeded)


def load_and_build(data_dir: Optional[Path] = None, **kw) -> Container:
    config = load_config(data_dir_override=data_dir)
    configure_logging(config)
    return build(config, **kw)
