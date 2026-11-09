"""Controllers translate widget events (strings) into input DTOs, call use cases and return Outcomes."""
from __future__ import annotations

import functools
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional

from ..application.dto import (AdjustStockInput, ApplyDiscountInput, ApproverCredentials, CategoryView,
                               CloseShiftInput, CompleteSaleInput, CustomerView, EditCartInput,
                               OpenShiftInput, PaymentInput, ProductView, RefundInput, ReportInput,
                               ScanItemInput, UserInput, UserView)
from ..application.errors import AppError, InvalidInput
from ..application.permissions import Permission, has_permission
from ..domain.entities import Role
from ..domain.errors import DomainError
from .formatting import opt, parse_date, parse_decimal, parse_money, parse_signed_money
from .presenters import Outcome, Presenter


class Session:
    """Who is logged in and which presenter (locale) is active."""

    def __init__(self, translator_factory: Callable[[str], object], default_locale: str = "en"):
        self._factory = translator_factory
        self.user: Optional[UserView] = None
        self.arabic_digits = False
        self.presenter = Presenter(translator_factory(default_locale), self.arabic_digits)

    def set_locale(self, locale: str) -> None:
        self.presenter = Presenter(self._factory(locale), self.arabic_digits)

    def login(self, user: UserView) -> None:
        self.user = user
        self.set_locale(user.locale)

    def logout(self) -> None:
        self.user = None

    @property
    def user_id(self) -> str:
        assert self.user is not None, "no user logged in"
        return self.user.id

    def can(self, permission: Permission) -> bool:
        return self.user is not None and has_permission(Role(self.user.role), permission)


def guarded(fn):
    """Convert domain/application errors into a localized Outcome; anything else is a bug and propagates
    as an 'unexpected' outcome after being logged by the caller."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except (DomainError, AppError) as exc:
            return self.s.presenter.error(exc)
        except ValueError as exc:   # bad widget text such as an invalid Decimal
            return self.s.presenter.error(InvalidInput(str(exc)))
    return wrapper


class _Base:
    def __init__(self, session: Session):
        self.s = session

    @property
    def p(self) -> Presenter:
        return self.s.presenter


def credentials(username: str, secret: str) -> Optional[ApproverCredentials]:
    username, secret = (username or "").strip(), secret or ""
    return ApproverCredentials(username, secret) if username else None


# ---------------------------------------------------------------------------
class AuthController(_Base):
    def __init__(self, session, auth, admin):
        super().__init__(session)
        self._auth, self._admin = auth, admin

    @guarded
    def login(self, username: str, secret: str) -> Outcome:
        user = self._auth.login(username, secret)
        self.s.login(user)
        return Outcome(user)

    @guarded
    def unlock(self, secret: str) -> Outcome:
        return Outcome(self._auth.unlock(self.s.user_id, secret))

    def lock(self) -> None:
        if self.s.user:
            self._auth.lock(self.s.user_id)

    def logout(self) -> None:
        self.s.logout()

    @guarded
    def toggle_locale(self) -> Outcome:
        locale = "en" if self.p.locale == "ar" else "ar"
        self._admin.set_locale(self.s.user_id, locale)
        self.s.set_locale(locale)
        self.s.user = replace(self.s.user, locale=locale)
        return Outcome(locale)

    def idle_minutes(self) -> int:
        try:
            return max(1, int(self._admin.get_settings(self.s.user_id).get("idle_lock_minutes", "5")))
        except (ValueError, DomainError, AppError):
            return 5


class CheckoutController(_Base):
    def __init__(self, session, checkout, catalogue):
        super().__init__(session)
        self._co, self._cat = checkout, catalogue
        self.sale_id: Optional[str] = None
        self.customer: Optional[CustomerView] = None

    def _cart(self, view) -> Outcome:
        if view.status != "DRAFT":
            self.sale_id = None
        else:
            self.sale_id = view.sale_id
        return Outcome(self.p.cart(view))

    def new_sale(self) -> None:
        self.sale_id, self.customer = None, None

    @guarded
    def scan(self, code: str, qty_text: str = "1") -> Outcome:
        if not code.strip():
            raise InvalidInput("empty code")
        qty = parse_decimal(qty_text or "1")
        return self._cart(self._co.scan_item(ScanItemInput(self.s.user_id, self.sale_id, code, qty)))

    @guarded
    def set_quantity(self, line_no: int, qty_text: str) -> Outcome:
        return self._cart(self._co.edit_cart(EditCartInput(
            self.s.user_id, self._need_sale(), "SET_QTY", line_no, parse_decimal(qty_text))))

    @guarded
    def remove_line(self, line_no: int) -> Outcome:
        return self._cart(self._co.edit_cart(EditCartInput(self.s.user_id, self._need_sale(), "REMOVE", line_no)))

    @guarded
    def void_cart(self) -> Outcome:
        view = self._co.edit_cart(EditCartInput(self.s.user_id, self._need_sale(), "VOID"))
        self.new_sale()
        return Outcome(self.p.cart(view))

    @guarded
    def discount(self, target: str, kind: str, value_text: str, line_no: Optional[int] = None,
                 approver_user: str = "", approver_secret: str = "") -> Outcome:
        value = parse_decimal(value_text) if kind == "PERCENT" else Decimal(parse_money(value_text))
        return self._cart(self._co.apply_discount(ApplyDiscountInput(
            self.s.user_id, self._need_sale(), target, kind, value, line_no,
            credentials(approver_user, approver_secret))))

    @guarded
    def pay_cash(self, tendered_text: str, total_raw: int) -> Outcome:
        tendered = parse_money(tendered_text) if tendered_text.strip() else total_raw
        return self._complete([PaymentInput("CASH", total_raw, tendered)])

    def change_preview(self, tendered_text: str, total_raw: int) -> str:
        try:
            tendered = parse_money(tendered_text) if tendered_text.strip() else total_raw
        except (InvalidInput, ValueError):
            return ""
        return self.p.fmt.money(max(0, tendered - total_raw))

    @guarded
    def pay_card(self, reference: str, total_raw: int) -> Outcome:
        return self._complete([PaymentInput("CARD", total_raw, None, reference.strip())])

    @guarded
    def pay_split(self, cash_text: str, card_reference: str, total_raw: int) -> Outcome:
        cash = parse_money(cash_text)
        if not 0 < cash < total_raw:
            raise InvalidInput("cash part must be between 0 and the total")
        return self._complete([PaymentInput("CASH", cash, cash),
                               PaymentInput("CARD", total_raw - cash, None, card_reference.strip())])

    def _complete(self, payments) -> Outcome:
        receipt = self._co.complete_sale(CompleteSaleInput(
            self.s.user_id, self._need_sale(), payments, self.customer.id if self.customer else None))
        self.new_sale()
        return Outcome(receipt, message=self.p.sale_done(receipt))

    @guarded
    def park(self) -> Outcome:
        self._co.park_sale(self.s.user_id, self._need_sale())
        self.new_sale()
        return Outcome(message=self.p.t("msg.parked"))

    @guarded
    def parked(self) -> Outcome:
        rows = [(v.sale_id, self.p.fmt.datetime(v.created_at), self.p.fmt.number(v.lines), self.p.fmt.money(v.total))
                for v in self._co.list_parked(self.s.user_id)]
        return Outcome(rows)

    @guarded
    def recall(self, sale_id: str) -> Outcome:
        return self._cart(self._co.recall_sale(self.s.user_id, sale_id))

    @guarded
    def reprint(self, number_text: str) -> Outcome:
        r = self._co.reprint_receipt(self.s.user_id, int(parse_decimal(number_text)))
        return Outcome(r, message=self.p.t("msg.reprinted" if r.printed else "msg.print_failed"))

    @guarded
    def find_products(self, query: str) -> Outcome:
        return Outcome(self._cat.search_products(self.s.user_id, query, include_inactive=False, limit=100))

    @guarded
    def find_customers(self, query: str) -> Outcome:
        return Outcome(self._cat.search_customers(self.s.user_id, query))

    @guarded
    def add_customer(self, name: str, phone: str, loyalty: str) -> Outcome:
        return Outcome(self._cat.save_customer(self.s.user_id, CustomerView(None, name, opt(phone), opt(loyalty))))

    def attach_customer(self, customer: Optional[CustomerView]) -> None:
        self.customer = customer

    def _need_sale(self) -> str:
        if not self.sale_id:
            raise InvalidInput("no active sale")
        return self.sale_id


class RefundController(_Base):
    def __init__(self, session, refunds):
        super().__init__(session)
        self._r = refunds

    @guarded
    def lookup(self, number_text: str) -> Outcome:
        v = self._r.lookup(self.s.user_id, int(parse_decimal(number_text)))
        f = self.p.fmt
        rows = [(l.line_no, self.p.name(l.name, l.name_ar), f.qty(l.sold), f.qty(l.refunded), f.qty(l.remaining))
                for l in v.lines]
        return Outcome((v, rows))

    @guarded
    def refund(self, number_text: str, quantities: dict[int, str], method: str, reason: str,
               approver_user: str = "", approver_secret: str = "") -> Outcome:
        lines = [(n, parse_decimal(q)) for n, q in quantities.items() if q.strip() and parse_decimal(q) > 0]
        r = self._r.process_refund(RefundInput(
            self.s.user_id, int(parse_decimal(number_text)), lines, method, reason.strip(),
            credentials(approver_user, approver_secret)))
        return Outcome(r, message=self.p.refund_done(r))


class ShiftController(_Base):
    def __init__(self, session, shifts):
        super().__init__(session)
        self._sh = shifts

    @guarded
    def current(self) -> Outcome:
        return Outcome(self._sh.current(self.s.user_id))

    @guarded
    def open(self, float_text: str) -> Outcome:
        v = self._sh.open_shift(OpenShiftInput(self.s.user_id, parse_money(float_text or "0")))
        return Outcome(v, message=self.p.t("msg.shift_opened"))

    @guarded
    def close(self, shift_id: str, counted_text: str, force_void: bool = False,
              approver_user: str = "", approver_secret: str = "") -> Outcome:
        z = self._sh.close_shift(CloseShiftInput(
            self.s.user_id, shift_id, parse_money(counted_text), None,
            credentials(approver_user, approver_secret), force_void))
        return Outcome(self.p.z_report(z), message=self.p.t("msg.shift_closed"))


class CatalogueController(_Base):
    def __init__(self, session, catalogue):
        super().__init__(session)
        self._c = catalogue

    @guarded
    def products(self, query: str = "") -> Outcome:
        return Outcome(self._c.search_products(self.s.user_id, query, True, 300))

    @guarded
    def categories(self) -> Outcome:
        return Outcome(self._c.list_categories(self.s.user_id))

    @guarded
    def save_product(self, product_id: Optional[str], form: dict) -> Outcome:
        view = ProductView(
            id=product_id, sku=form["sku"], barcode=opt(form.get("barcode")), name_ar=form["name_ar"],
            name_en=form["name_en"], category_id=opt(form.get("category_id")), price=parse_money(form["price"]),
            cost=parse_money(form.get("cost") or "0"), unit=form.get("unit", "PIECE"),
            reorder_level=parse_decimal(form.get("reorder") or "0"), is_active=bool(form.get("active", True)))
        return Outcome(self._c.save_product(self.s.user_id, view), message=self.p.t("msg.saved"))

    @guarded
    def set_active(self, product_id: str, active: bool) -> Outcome:
        self._c.set_product_active(self.s.user_id, product_id, active)
        return Outcome(message=self.p.t("msg.saved"))

    @guarded
    def save_category(self, category_id: Optional[str], name_ar: str, name_en: str, tax_percent: str,
                      inclusive: bool) -> Outcome:
        bp = int(parse_decimal(tax_percent or "0") * 100)
        return Outcome(self._c.save_category(self.s.user_id, CategoryView(category_id, name_ar, name_en, bp, inclusive)),
                       message=self.p.t("msg.saved"))

    @guarded
    def customers(self, query: str = "") -> Outcome:
        return Outcome(self._c.search_customers(self.s.user_id, query))

    @guarded
    def save_customer(self, customer_id: Optional[str], name: str, phone: str, loyalty: str) -> Outcome:
        return Outcome(self._c.save_customer(self.s.user_id, CustomerView(customer_id, name, opt(phone), opt(loyalty))),
                       message=self.p.t("msg.saved"))

    # stock
    @guarded
    def adjust_stock(self, product_id: str, kind: str, qty_text: str, reason: str) -> Outcome:
        lvl = self._c.adjust_stock(AdjustStockInput(self.s.user_id, product_id, kind, parse_decimal(qty_text), reason.strip()))
        msg = self.p.t("msg.stock_low" if lvl.below_reorder else "msg.saved")
        return Outcome(lvl, message=msg)

    @guarded
    def low_stock(self) -> Outcome:
        return Outcome(self._c.low_stock(self.s.user_id))


class ReportController(_Base):
    def __init__(self, session, reports, exports_dir: Path):
        super().__init__(session)
        self._r, self._dir = reports, exports_dir

    def default_range(self) -> tuple[str, str]:
        today = date.today()
        return (today - timedelta(days=6)).isoformat(), today.isoformat()

    def _input(self, kind: str, from_text: str, to_text: str) -> ReportInput:
        return ReportInput(self.s.user_id, kind, parse_date(from_text), parse_date(to_text))

    @guarded
    def run(self, kind: str, from_text: str, to_text: str) -> Outcome:
        return Outcome(self.p.report(self._r.generate(self._input(kind, from_text, to_text))))

    @guarded
    def export(self, kind: str, from_text: str, to_text: str, path: Optional[Path] = None) -> Outcome:
        path = path or self._dir / f"{kind.lower()}-{from_text}-{to_text}.csv"
        out = self._r.export_csv(self._input(kind, from_text, to_text), Path(path))
        return Outcome(out, message=self.p.t("msg.exported", path=str(out)))


class AdminController(_Base):
    def __init__(self, session, admin):
        super().__init__(session)
        self._a = admin

    @guarded
    def users(self) -> Outcome:
        return Outcome(self._a.list_users(self.s.user_id))

    @guarded
    def save_user(self, user_id: Optional[str], username: str, display: str, role: str, locale: str,
                  active: bool, password: str, pin: str) -> Outcome:
        return Outcome(self._a.save_user(self.s.user_id, UserInput(
            user_id, username, display, role, locale, active, opt(password), opt(pin))),
            message=self.p.t("msg.saved"))

    @guarded
    def settings(self) -> Outcome:
        return Outcome(self._a.get_settings(self.s.user_id))

    @guarded
    def save_settings(self, values: dict[str, str]) -> Outcome:
        self._a.save_settings(self.s.user_id, values)
        return Outcome(message=self.p.t("msg.saved"))

    @guarded
    def audit(self, limit: int = 200) -> Outcome:
        rows = [(self.p.fmt.datetime(at), user, action, entity,
                 ", ".join(f"{k}={v}" for k, v in details.items()))
                for at, user, action, entity, details in self._a.recent_audit(self.s.user_id, limit)]
        return Outcome(rows)

    @guarded
    def backups(self) -> Outcome:
        return Outcome([(b.path, self.p.fmt.datetime(b.created_at), f"{b.size_bytes // 1024} KB")
                        for b in self._a.list_backups(self.s.user_id)])

    @guarded
    def backup_now(self) -> Outcome:
        info = self._a.backup_now(self.s.user_id)
        return Outcome(info, message=self.p.t("msg.backup_done", path=info.path))

    @guarded
    def restore(self, path: str) -> Outcome:
        self._a.restore(self.s.user_id, Path(path))
        return Outcome(message=self.p.t("msg.restored"))
