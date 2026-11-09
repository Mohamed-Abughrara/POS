"""Presenters turn DTOs and errors into view-models (formatted, localized strings)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..application.dto import (CartView, CategoryView, ProductView, RefundableSaleView, RefundReceipt,
                               ReportView, SaleReceipt, ShiftView, UserView, ZReport)
from ..application.errors import AppError
from ..domain.errors import DomainError
from .formatting import Formatter

MONEY_COLUMNS = {"gross", "discounts", "tax", "total", "refunds", "net", "amount"}


class Translator(Protocol):
    locale: str

    def t(self, key: str, **kw) -> str: ...
    def has(self, key: str) -> bool: ...


@dataclass(frozen=True)
class LineVM:
    line_no: int
    name: str
    qty: str
    unit_price: str
    discount: str
    tax: str
    total: str


@dataclass(frozen=True)
class CartVM:
    sale_id: str
    status: str
    lines: list[LineVM]
    subtotal: str
    discount: str
    tax: str
    total: str
    total_raw: int
    paid: str
    balance: str
    is_empty: bool
    can_pay: bool


@dataclass(frozen=True)
class ReportVM:
    title: str
    columns: list[str]
    rows: list[list[str]]
    totals: list[str]


@dataclass(frozen=True)
class Outcome:
    """What a controller hands to a view: either a value or a localized error."""
    value: object = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    message: Optional[str] = None      # optional success message

    @property
    def ok(self) -> bool:
        return self.error is None


class Presenter:
    def __init__(self, translator: Translator, arabic_digits: bool = False):
        self.tr = translator
        self.fmt = Formatter(translator.locale, arabic_digits)

    @property
    def locale(self) -> str:
        return self.tr.locale

    def t(self, key: str, **kw) -> str:
        return self.tr.t(key, **kw)

    # ---- errors ------------------------------------------------------------
    def error(self, exc: Exception) -> Outcome:
        name = exc.__class__.__name__
        key = f"err.{name}"
        if isinstance(exc, (DomainError, AppError)) and self.tr.has(key):
            text = self.tr.t(key)
        else:
            text = self.tr.t("err.Unexpected")
        detail = str(exc)
        if isinstance(exc, (DomainError, AppError)) and detail and detail != name and name in (
                "InvalidInput", "DuplicateEntity", "BackupError", "InvalidEntity", "InvalidAmount"):
            text += f" ({detail})"
        return Outcome(error=text, error_type=name)

    # ---- cart --------------------------------------------------------------
    def name(self, en: str, ar: str) -> str:
        return (ar or en) if self.locale == "ar" else (en or ar)

    def cart(self, c: CartView) -> CartVM:
        f = self.fmt
        lines = [LineVM(l.line_no, self.name(l.name, l.name_ar), f.qty(l.quantity),
                        f.money(l.unit_price, False), f.money(l.line_discount, False) if l.line_discount else "",
                        f.money(l.tax, False) if l.tax else "", f.money(l.total, False)) for l in c.lines]
        return CartVM(c.sale_id, c.status, lines, f.money(c.subtotal), f.money(c.discount_total),
                      f.money(c.tax_total), f.money(c.total), c.total, f.money(c.paid),
                      f.money(c.balance_due), not c.lines, bool(c.lines) and c.status == "DRAFT")

    def sale_done(self, r: SaleReceipt) -> str:
        parts = [self.t("msg.sale_done", number=self.fmt.number(r.number), total=self.fmt.money(r.total))]
        if r.change_due:
            parts.append(self.t("msg.change_due", change=self.fmt.money(r.change_due)))
        if not r.printed:
            parts.append(self.t("msg.print_failed"))
        return "  ".join(parts)

    def refund_done(self, r: RefundReceipt) -> str:
        text = self.t("msg.refund_done", amount=self.fmt.money(r.amount))
        return text if r.printed else text + "  " + self.t("msg.print_failed")

    def z_report(self, z: ZReport) -> list[tuple[str, str]]:
        f, t = self.fmt, self.t
        rows = [(t("z.cashier"), z.cashier_name), (t("z.opened"), f.datetime(z.opened_at)),
                (t("z.closed"), f.datetime(z.closed_at)), (t("z.sales"), f.number(z.sales_count)),
                (t("z.gross"), f.money(z.gross)), (t("z.discounts"), f.money(z.discounts)),
                (t("z.tax"), f.money(z.tax)), (t("z.refunds"), f.money(z.refunds)),
                (t("z.net"), f.money(z.net))]
        rows += [(t("method." + m), f.money(a)) for m, a in sorted(z.by_method.items())]
        rows += [(t("z.opening_float"), f.money(z.opening_float)), (t("z.expected"), f.money(z.expected_cash)),
                 (t("z.counted"), f.money(z.counted_cash)), (t("z.variance"), f.money(z.variance))]
        return rows

    # ---- reports -----------------------------------------------------------
    def report(self, r: ReportView) -> ReportVM:
        f = self.fmt
        money_idx = {i for i, c in enumerate(r.columns) if c in MONEY_COLUMNS}

        def cell(i: int, v) -> str:
            if i in money_idx and isinstance(v, int):
                return f.money(v, False)
            if r.columns[i] == "method" and isinstance(v, str):
                return self.t("method." + v) if self.tr.has("method." + v) else v
            if isinstance(v, float):
                return f.qty(__import__("decimal").Decimal(str(v)))
            return f.number(v) if isinstance(v, int) else str(v)

        rows = [[cell(i, v) for i, v in enumerate(row)] for row in r.rows]
        totals = [self.t("report.total") if i == 0 else (cell(i, v) if v != "" else "") for i, v in enumerate(r.totals)]
        return ReportVM(self.t("report." + r.title), [self.t("col." + c) for c in r.columns], rows, totals)

    # ---- misc --------------------------------------------------------------
    def product_row(self, p: ProductView) -> tuple:
        f = self.fmt
        return (p.sku, p.barcode or "", self.name(p.name_en, p.name_ar), f.money(p.price, False),
                f.qty(p.on_hand) if p.on_hand is not None else "",
                self.t("yes") if p.is_active else self.t("no"))

    def shift_text(self, s: Optional[ShiftView]) -> str:
        if s is None:
            return self.t("shift.none")
        return self.t("shift.open_since", time=self.fmt.datetime(s.opened_at))

    def user_label(self, u: UserView) -> str:
        return f"{u.display_name} ({self.t('role.' + u.role)})"

    def category_label(self, c: CategoryView) -> str:
        return self.name(c.name_en, c.name_ar)
