"""SQLite implementations of the application ports. All writes happen inside a UnitOfWork."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from typing import Optional

from ...domain.discount import Discount, DiscountKind
from ...domain.entities import (AuditEntry, Category, Customer, MovementType, Product, Role, Shift,
                                ShiftStatus, StockMovement, User)
from ...domain.errors import SaleNotEditable
from ...domain.money import Money
from ...domain.quantity import Quantity, Unit
from ...domain.refund import Refund, RefundLine
from ...domain.sale import Payment, PaymentMethod, Sale, SaleLine, SaleStatus
from ...domain.tax import TaxRate


def to_milli(d: Decimal) -> int:
    return int(Decimal(d) * 1000)


def from_milli(i: int) -> Decimal:
    return Decimal(i).scaleb(-3)


def _dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat(timespec="seconds") if d else None


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class _Repo:
    def __init__(self, conn: sqlite3.Connection):
        self.c = conn


# ---------------------------------------------------------------------------
class SqliteCategoryRepository(_Repo):
    @staticmethod
    def _row(r) -> Category:
        return Category(r["id"], r["name_ar"], r["name_en"], TaxRate(r["tax_bp"], bool(r["tax_inclusive"])))

    def get(self, category_id):
        r = self.c.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
        return self._row(r) if r else None

    def list(self):
        return [self._row(r) for r in self.c.execute("SELECT * FROM categories ORDER BY name_en")]

    def save(self, cat: Category):
        self.c.execute(
            "INSERT INTO categories(id,name_ar,name_en,tax_bp,tax_inclusive) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name_ar=excluded.name_ar,name_en=excluded.name_en,"
            "tax_bp=excluded.tax_bp,tax_inclusive=excluded.tax_inclusive",
            (cat.id, cat.name_ar, cat.name_en, cat.tax_rate.basis_points, int(cat.tax_rate.inclusive)))


_PRODUCT_SQL = ("SELECT p.*, COALESCE(c.tax_bp,0) AS tax_bp, COALESCE(c.tax_inclusive,0) AS tax_inclusive "
                "FROM products p LEFT JOIN categories c ON c.id = p.category_id ")


def _product(r) -> Product:
    return Product(
        id=r["id"], sku=r["sku"], barcode=r["barcode"], name_ar=r["name_ar"], name_en=r["name_en"],
        category_id=r["category_id"], price=Money(r["price"]), cost=Money(r["cost"]),
        unit=Unit(r["unit"]), reorder_level=from_milli(r["reorder_milli"]), is_active=bool(r["is_active"]),
        tax_rate=TaxRate(r["tax_bp"], bool(r["tax_inclusive"])))


class SqliteProductRepository(_Repo):
    def get(self, product_id):
        r = self.c.execute(_PRODUCT_SQL + "WHERE p.id=?", (product_id,)).fetchone()
        return _product(r) if r else None

    def get_by_barcode(self, barcode):
        r = self.c.execute(_PRODUCT_SQL + "WHERE p.barcode=?", (barcode,)).fetchone()
        return _product(r) if r else None

    def get_by_sku(self, sku):
        r = self.c.execute(_PRODUCT_SQL + "WHERE p.sku=?", (sku,)).fetchone()
        return _product(r) if r else None

    def search(self, query, limit=50, include_inactive=False):
        sql, args = _PRODUCT_SQL + "WHERE 1=1 ", []
        if not include_inactive:
            sql += "AND p.is_active=1 "
        if query.strip():
            like = _like(query.strip())
            sql += ("AND (p.sku LIKE ? ESCAPE '\\' OR p.barcode LIKE ? ESCAPE '\\' "
                    "OR p.name_en LIKE ? ESCAPE '\\' OR p.name_ar LIKE ? ESCAPE '\\') ")
            args += [like] * 4
        sql += "ORDER BY p.name_en, p.name_ar LIMIT ?"
        return [_product(r) for r in self.c.execute(sql, (*args, limit))]

    def save(self, p: Product):
        self.c.execute(
            "INSERT INTO products(id,sku,barcode,name_ar,name_en,category_id,price,cost,unit,reorder_milli,is_active)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET sku=excluded.sku,"
            "barcode=excluded.barcode,name_ar=excluded.name_ar,name_en=excluded.name_en,"
            "category_id=excluded.category_id,price=excluded.price,cost=excluded.cost,unit=excluded.unit,"
            "reorder_milli=excluded.reorder_milli,is_active=excluded.is_active",
            (p.id, p.sku, p.barcode, p.name_ar, p.name_en, p.category_id, p.price.amount, p.cost.amount,
             p.unit.value, to_milli(p.reorder_level), int(p.is_active)))


# ---------------------------------------------------------------------------
class SqliteCustomerRepository(_Repo):
    @staticmethod
    def _row(r):
        return Customer(r["id"], r["name"], r["phone"], r["loyalty_id"])

    def get(self, customer_id):
        r = self.c.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        return self._row(r) if r else None

    def search(self, query, limit=50):
        like = _like(query.strip())
        rows = self.c.execute(
            "SELECT * FROM customers WHERE name LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\' "
            "OR loyalty_id LIKE ? ESCAPE '\\' ORDER BY name LIMIT ?", (like, like, like, limit))
        return [self._row(r) for r in rows]

    def save(self, c: Customer):
        self.c.execute(
            "INSERT INTO customers(id,name,phone,loyalty_id) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE "
            "SET name=excluded.name,phone=excluded.phone,loyalty_id=excluded.loyalty_id",
            (c.id, c.name, c.phone, c.loyalty_id))


class SqliteUserRepository(_Repo):
    @staticmethod
    def _row(r):
        return User(r["id"], r["username"], r["display_name"], Role(r["role"]), r["password_hash"],
                    r["pin_hash"], bool(r["is_active"]), r["locale"])

    def get(self, user_id):
        r = self.c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return self._row(r) if r else None

    def get_by_username(self, username):
        r = self.c.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username.strip(),)).fetchone()
        return self._row(r) if r else None

    def list(self):
        return [self._row(r) for r in self.c.execute("SELECT * FROM users ORDER BY username")]

    def save(self, u: User):
        self.c.execute(
            "INSERT INTO users(id,username,display_name,role,password_hash,pin_hash,is_active,locale)"
            " VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username,"
            "display_name=excluded.display_name,role=excluded.role,password_hash=excluded.password_hash,"
            "pin_hash=excluded.pin_hash,is_active=excluded.is_active,locale=excluded.locale",
            (u.id, u.username, u.display_name, u.role.value, u.password_hash, u.pin_hash,
             int(u.is_active), u.locale))


class SqliteShiftRepository(_Repo):
    @staticmethod
    def _row(r):
        return Shift(r["id"], r["cashier_id"], _dt(r["opened_at"]), Money(r["opening_float"]),
                     ShiftStatus(r["status"]), _dt(r["closed_at"]),
                     Money(r["counted_cash"]) if r["counted_cash"] is not None else None,
                     Money(r["expected_cash"]) if r["expected_cash"] is not None else None)

    def get(self, shift_id):
        r = self.c.execute("SELECT * FROM shifts WHERE id=?", (shift_id,)).fetchone()
        return self._row(r) if r else None

    def get_open(self):
        r = self.c.execute("SELECT * FROM shifts WHERE status='OPEN'").fetchone()
        return self._row(r) if r else None

    def save(self, s: Shift):
        self.c.execute(
            "INSERT INTO shifts(id,cashier_id,opened_at,opening_float,closed_at,counted_cash,expected_cash,status)"
            " VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET closed_at=excluded.closed_at,"
            "counted_cash=excluded.counted_cash,expected_cash=excluded.expected_cash,status=excluded.status",
            (s.id, s.cashier_id, _iso(s.opened_at), s.opening_float.amount, _iso(s.closed_at),
             s.counted_cash.amount if s.counted_cash else None,
             s.expected_cash.amount if s.expected_cash else None, s.status.value))


# ---------------------------------------------------------------------------
class SqliteSaleRepository(_Repo):
    def _load(self, r) -> Sale:
        cd = None
        if r["cart_discount_kind"]:
            cd = Discount(DiscountKind(r["cart_discount_kind"]), Decimal(r["cart_discount_value"]))
        sale = Sale(id=r["id"], shift_id=r["shift_id"], cashier_id=r["cashier_id"],
                    created_at=_dt(r["created_at"]), number=r["number"], customer_id=r["customer_id"],
                    cart_discount=cd, status=SaleStatus(r["status"]), completed_at=_dt(r["completed_at"]))
        for l in self.c.execute("SELECT * FROM sale_lines WHERE sale_id=? ORDER BY line_no", (sale.id,)):
            disc = Discount(DiscountKind(l["disc_kind"]), Decimal(l["disc_value"])) if l["disc_kind"] else None
            sale.lines.append(SaleLine(
                l["line_no"], l["product_id"], l["name"], l["name_ar"], Money(l["unit_price"]),
                Quantity(from_milli(l["qty_milli"]), Unit(l["unit"])),
                TaxRate(l["tax_bp"], bool(l["tax_inclusive"])), disc))
        for p in self.c.execute("SELECT * FROM payments WHERE sale_id=? ORDER BY id", (sale.id,)):
            sale.payments.append(Payment(PaymentMethod(p["method"]), Money(p["amount"]),
                                         Money(p["tendered"]) if p["tendered"] is not None else None,
                                         p["reference"]))
        return sale

    def get(self, sale_id):
        r = self.c.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
        return self._load(r) if r else None

    def find_by_number(self, number):
        r = self.c.execute("SELECT * FROM sales WHERE number=?", (number,)).fetchone()
        return self._load(r) if r else None

    def next_number(self):
        return self.c.execute("SELECT COALESCE(MAX(number),0)+1 FROM sales").fetchone()[0]

    def list_parked(self, shift_id=None):
        sql, args = "SELECT * FROM sales WHERE status='PARKED'", ()
        if shift_id:
            sql, args = sql + " AND shift_id=?", (shift_id,)
        return [self._load(r) for r in self.c.execute(sql + " ORDER BY created_at", args)]

    def mark_printed(self, sale_id, printed):
        self.c.execute("UPDATE sales SET printed=? WHERE id=?", (int(printed), sale_id))

    def save(self, sale: Sale):
        existing = self.c.execute("SELECT status FROM sales WHERE id=?", (sale.id,)).fetchone()
        if existing and existing["status"] == "COMPLETED":
            raise SaleNotEditable("completed sales are immutable")
        t = sale.totals()
        cd = sale.cart_discount
        self.c.execute("DELETE FROM payments WHERE sale_id=?", (sale.id,))
        self.c.execute("DELETE FROM sale_lines WHERE sale_id=?", (sale.id,))
        self.c.execute(
            "INSERT INTO sales(id,number,shift_id,cashier_id,customer_id,cart_discount_kind,cart_discount_value,"
            "status,created_at,completed_at,subtotal,discount_total,tax_total,total) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET number=excluded.number,"
            "customer_id=excluded.customer_id,cart_discount_kind=excluded.cart_discount_kind,"
            "cart_discount_value=excluded.cart_discount_value,status=excluded.status,"
            "completed_at=excluded.completed_at,subtotal=excluded.subtotal,"
            "discount_total=excluded.discount_total,tax_total=excluded.tax_total,total=excluded.total",
            (sale.id, sale.number, sale.shift_id, sale.cashier_id, sale.customer_id,
             cd.kind.value if cd else None, str(cd.value) if cd else None, sale.status.value,
             _iso(sale.created_at), _iso(sale.completed_at), t.subtotal.amount, t.discount_total.amount,
             t.tax_total.amount, t.total.amount))
        by_no = {lt.line_no: lt for lt in t.lines}
        for l in sale.lines:
            d = l.line_discount
            self.c.execute(
                "INSERT INTO sale_lines(sale_id,line_no,product_id,name,name_ar,unit_price,qty_milli,unit,"
                "tax_bp,tax_inclusive,disc_kind,disc_value,line_tax,line_total) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sale.id, l.line_no, l.product_id, l.name, l.name_ar, l.unit_price.amount,
                 to_milli(l.quantity.value), l.quantity.unit.value, l.tax_rate.basis_points,
                 int(l.tax_rate.inclusive), d.kind.value if d else None, str(d.value) if d else None,
                 by_no[l.line_no].tax.amount, by_no[l.line_no].total.amount))
        for p in sale.payments:
            self.c.execute("INSERT INTO payments(sale_id,method,amount,tendered,reference) VALUES(?,?,?,?,?)",
                           (sale.id, p.method.value, p.amount.amount,
                            p.tendered.amount if p.tendered else None, p.reference))


class SqliteRefundRepository(_Repo):
    def next_number(self):
        return self.c.execute("SELECT COALESCE(MAX(number),0)+1 FROM refunds").fetchone()[0]

    def save(self, r: Refund):
        self.c.execute(
            "INSERT INTO refunds(id,number,original_sale_id,shift_id,method,approved_by,reason,created_at,amount)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (r.id, r.number, r.original_sale_id, r.shift_id, r.method.value, r.approved_by, r.reason,
             _iso(r.created_at), r.amount.amount))
        for l in r.lines:
            self.c.execute("INSERT INTO refund_lines(refund_id,line_no,product_id,name,qty_milli,amount)"
                           " VALUES(?,?,?,?,?,?)",
                           (r.id, l.line_no, l.product_id, l.name, to_milli(l.quantity), l.amount.amount))

    def list_for_sale(self, sale_id):
        out = []
        for r in self.c.execute("SELECT * FROM refunds WHERE original_sale_id=? ORDER BY number", (sale_id,)):
            lines = [RefundLine(l["line_no"], l["product_id"], l["name"], from_milli(l["qty_milli"]),
                                Money(l["amount"]))
                     for l in self.c.execute("SELECT * FROM refund_lines WHERE refund_id=? ORDER BY line_no",
                                             (r["id"],))]
            out.append(Refund(r["id"], r["original_sale_id"], r["shift_id"], PaymentMethod(r["method"]),
                              r["approved_by"], r["reason"], _dt(r["created_at"]), lines, r["number"]))
        return out


# ---------------------------------------------------------------------------
class SqliteStockLedger(_Repo):
    def append(self, m: StockMovement):
        self.c.execute(
            "INSERT INTO stock_movements(id,product_id,type,qty_milli,ref_id,user_id,at,reason) VALUES(?,?,?,?,?,?,?,?)",
            (m.id, m.product_id, m.type.value, to_milli(m.qty_delta), m.ref_id, m.user_id, _iso(m.at), m.reason))

    def on_hand(self, product_id):
        v = self.c.execute("SELECT COALESCE(SUM(qty_milli),0) FROM stock_movements WHERE product_id=?",
                           (product_id,)).fetchone()[0]
        return from_milli(v)

    def low_stock(self):
        rows = self.c.execute(
            _PRODUCT_SQL.replace("SELECT p.*,", "SELECT p.*, COALESCE((SELECT SUM(qty_milli) FROM stock_movements "
                                 "WHERE product_id=p.id),0) AS on_hand_milli,") +
            "WHERE p.is_active=1 AND COALESCE((SELECT SUM(qty_milli) FROM stock_movements WHERE product_id=p.id),0)"
            " <= p.reorder_milli ORDER BY p.name_en")
        return [(_product(r), from_milli(r["on_hand_milli"])) for r in rows]


class SqliteAuditLog(_Repo):
    def append(self, e: AuditEntry):
        self.c.execute("INSERT INTO audit_log(id,at,user_id,action,entity,entity_id,details_json) VALUES(?,?,?,?,?,?,?)",
                       (e.id, _iso(e.at), e.user_id, e.action, e.entity, e.entity_id,
                        json.dumps(e.details, ensure_ascii=False, default=str)))

    def recent(self, limit=200):
        return [AuditEntry(r["id"], _dt(r["at"]), r["user_id"], r["action"], r["entity"], r["entity_id"],
                           json.loads(r["details_json"]))
                for r in self.c.execute("SELECT * FROM audit_log ORDER BY seq DESC LIMIT ?", (limit,))]


class SqliteSettingsRepository(_Repo):
    def get(self, key, default=""):
        r = self.c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set(self, key, value):
        self.c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, value))

    def all(self):
        return {r["key"]: r["value"] for r in self.c.execute("SELECT key,value FROM settings")}
