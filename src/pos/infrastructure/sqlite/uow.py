from __future__ import annotations

import sqlite3

from .repositories import (SqliteAuditLog, SqliteCategoryRepository, SqliteCustomerRepository,
                           SqliteProductRepository, SqliteRefundRepository, SqliteSaleRepository,
                           SqliteSettingsRepository, SqliteShiftRepository, SqliteStockLedger,
                           SqliteUserRepository)


class SqliteUnitOfWork:
    """One transaction per `with` block; leaving without commit() rolls back."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self.products = SqliteProductRepository(conn)
        self.categories = SqliteCategoryRepository(conn)
        self.sales = SqliteSaleRepository(conn)
        self.refunds = SqliteRefundRepository(conn)
        self.shifts = SqliteShiftRepository(conn)
        self.customers = SqliteCustomerRepository(conn)
        self.users = SqliteUserRepository(conn)
        self.stock = SqliteStockLedger(conn)
        self.audit = SqliteAuditLog(conn)
        self.settings = SqliteSettingsRepository(conn)

    def __enter__(self):
        self._conn.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._conn.in_transaction:
            self._conn.execute("ROLLBACK")

    def commit(self):
        self._conn.execute("COMMIT")

    def rollback(self):
        if self._conn.in_transaction:
            self._conn.execute("ROLLBACK")


def uow_factory(conn: sqlite3.Connection):
    return lambda: SqliteUnitOfWork(conn)
