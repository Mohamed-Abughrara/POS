"""Forward-only migrations tracked with PRAGMA user_version."""
from __future__ import annotations

import sqlite3

V1 = """
CREATE TABLE categories(
    id TEXT PRIMARY KEY, name_ar TEXT NOT NULL, name_en TEXT NOT NULL,
    tax_bp INTEGER NOT NULL DEFAULT 0 CHECK(tax_bp BETWEEN 0 AND 10000),
    tax_inclusive INTEGER NOT NULL DEFAULT 0);

CREATE TABLE products(
    id TEXT PRIMARY KEY, sku TEXT NOT NULL UNIQUE, barcode TEXT UNIQUE,
    name_ar TEXT NOT NULL, name_en TEXT NOT NULL,
    category_id TEXT REFERENCES categories(id),
    price INTEGER NOT NULL CHECK(price >= 0), cost INTEGER NOT NULL DEFAULT 0 CHECK(cost >= 0),
    unit TEXT NOT NULL DEFAULT 'PIECE', reorder_milli INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1);
CREATE INDEX idx_products_name ON products(name_en, name_ar);

CREATE TABLE customers(
    id TEXT PRIMARY KEY, name TEXT NOT NULL, phone TEXT UNIQUE, loyalty_id TEXT);

CREATE TABLE users(
    id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('CASHIER','MANAGER','ADMIN')),
    password_hash TEXT NOT NULL, pin_hash TEXT,
    is_active INTEGER NOT NULL DEFAULT 1, locale TEXT NOT NULL DEFAULT 'en');

CREATE TABLE shifts(
    id TEXT PRIMARY KEY, cashier_id TEXT NOT NULL REFERENCES users(id),
    opened_at TEXT NOT NULL, opening_float INTEGER NOT NULL,
    closed_at TEXT, counted_cash INTEGER, expected_cash INTEGER,
    status TEXT NOT NULL CHECK(status IN ('OPEN','CLOSED')));
CREATE UNIQUE INDEX one_open_shift ON shifts(status) WHERE status = 'OPEN';

CREATE TABLE sales(
    id TEXT PRIMARY KEY, number INTEGER UNIQUE,
    shift_id TEXT NOT NULL REFERENCES shifts(id), cashier_id TEXT NOT NULL REFERENCES users(id),
    customer_id TEXT REFERENCES customers(id),
    cart_discount_kind TEXT, cart_discount_value TEXT,
    status TEXT NOT NULL CHECK(status IN ('DRAFT','PARKED','COMPLETED','VOIDED')),
    created_at TEXT NOT NULL, completed_at TEXT, printed INTEGER NOT NULL DEFAULT 0,
    subtotal INTEGER NOT NULL DEFAULT 0, discount_total INTEGER NOT NULL DEFAULT 0,
    tax_total INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0);
CREATE INDEX idx_sales_completed ON sales(completed_at);
CREATE INDEX idx_sales_status ON sales(status);

CREATE TABLE sale_lines(
    sale_id TEXT NOT NULL REFERENCES sales(id), line_no INTEGER NOT NULL,
    product_id TEXT NOT NULL REFERENCES products(id), name TEXT NOT NULL, name_ar TEXT NOT NULL,
    unit_price INTEGER NOT NULL, qty_milli INTEGER NOT NULL CHECK(qty_milli > 0), unit TEXT NOT NULL,
    tax_bp INTEGER NOT NULL, tax_inclusive INTEGER NOT NULL,
    disc_kind TEXT, disc_value TEXT,
    line_tax INTEGER NOT NULL DEFAULT 0, line_total INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(sale_id, line_no));

CREATE TABLE payments(
    id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id TEXT NOT NULL REFERENCES sales(id),
    method TEXT NOT NULL CHECK(method IN ('CASH','CARD')), amount INTEGER NOT NULL CHECK(amount > 0),
    tendered INTEGER, reference TEXT);

CREATE TABLE refunds(
    id TEXT PRIMARY KEY, number INTEGER UNIQUE, original_sale_id TEXT NOT NULL REFERENCES sales(id),
    shift_id TEXT NOT NULL REFERENCES shifts(id), method TEXT NOT NULL,
    approved_by TEXT NOT NULL REFERENCES users(id), reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, amount INTEGER NOT NULL);
CREATE INDEX idx_refunds_sale ON refunds(original_sale_id);

CREATE TABLE refund_lines(
    refund_id TEXT NOT NULL REFERENCES refunds(id), line_no INTEGER NOT NULL,
    product_id TEXT NOT NULL, name TEXT NOT NULL, qty_milli INTEGER NOT NULL, amount INTEGER NOT NULL,
    PRIMARY KEY(refund_id, line_no));

CREATE TABLE stock_movements(
    id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id),
    type TEXT NOT NULL CHECK(type IN ('SALE','REFUND','RECEIPT','ADJUSTMENT','WASTE')),
    qty_milli INTEGER NOT NULL, ref_id TEXT, user_id TEXT NOT NULL, at TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '');
CREATE INDEX idx_stock_product ON stock_movements(product_id);

CREATE TABLE audit_log(
    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, at TEXT NOT NULL, user_id TEXT,
    action TEXT NOT NULL, entity TEXT NOT NULL, entity_id TEXT, details_json TEXT NOT NULL DEFAULT '{}');

CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- Append-only ledgers
CREATE TRIGGER stock_no_update BEFORE UPDATE ON stock_movements BEGIN SELECT RAISE(ABORT, 'stock_movements is append-only'); END;
CREATE TRIGGER stock_no_delete BEFORE DELETE ON stock_movements BEGIN SELECT RAISE(ABORT, 'stock_movements is append-only'); END;
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

-- Completed sales are immutable (only the printed flag may change)
CREATE TRIGGER sales_completed_immutable BEFORE UPDATE ON sales
WHEN OLD.status = 'COMPLETED' AND (NEW.status <> OLD.status OR NEW.total <> OLD.total
     OR NEW.cashier_id <> OLD.cashier_id OR NEW.shift_id <> OLD.shift_id
     OR IFNULL(NEW.customer_id,'') <> IFNULL(OLD.customer_id,'') OR IFNULL(NEW.number,0) <> IFNULL(OLD.number,0))
BEGIN SELECT RAISE(ABORT, 'completed sales are immutable'); END;
CREATE TRIGGER sales_no_delete BEFORE DELETE ON sales WHEN OLD.status = 'COMPLETED'
BEGIN SELECT RAISE(ABORT, 'completed sales are immutable'); END;
CREATE TRIGGER lines_completed_no_delete BEFORE DELETE ON sale_lines
WHEN (SELECT status FROM sales WHERE id = OLD.sale_id) = 'COMPLETED'
BEGIN SELECT RAISE(ABORT, 'completed sales are immutable'); END;
CREATE TRIGGER payments_completed_no_delete BEFORE DELETE ON payments
WHEN (SELECT status FROM sales WHERE id = OLD.sale_id) = 'COMPLETED'
BEGIN SELECT RAISE(ABORT, 'completed sales are immutable'); END;
"""

MIGRATIONS = [V1]


def current_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> int:
    version = current_version(conn)
    for target, script in enumerate(MIGRATIONS, start=1):
        if target <= version:
            continue
        conn.executescript("BEGIN;\n" + script + f"\nPRAGMA user_version = {target};\nCOMMIT;")
    return current_version(conn)
