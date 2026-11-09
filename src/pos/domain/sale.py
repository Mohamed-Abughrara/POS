"""Sale aggregate root (with lines and payments)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from .discount import Discount
from .entities import Product
from .errors import (CardReferenceMissing, InsufficientPayment, InvalidAmount,
                     InvalidDiscount, InvalidEntity, InvalidQuantity, ProductInactive,
                     SaleNotEditable)
from .money import Money, round_half_up_div
from .quantity import Quantity
from .tax import TaxRate


class SaleStatus(str, Enum):
    DRAFT = "DRAFT"
    PARKED = "PARKED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"


@dataclass(frozen=True)
class Payment:
    method: PaymentMethod
    amount: Money                 # amount applied to the sale (excludes change)
    tendered: Optional[Money] = None  # cash handed over; change = tendered - amount
    reference: Optional[str] = None

    def __post_init__(self):
        if self.amount.amount <= 0:
            raise InvalidAmount("payment amount must be > 0")
        if self.method == PaymentMethod.CARD:
            if not (self.reference and self.reference.strip()):
                raise CardReferenceMissing("card payment requires a reference")
            if self.tendered is not None and self.tendered != self.amount:
                raise InvalidAmount("change only applies to cash")
        elif self.tendered is not None and self.tendered < self.amount:
            raise InvalidAmount("tendered cash is less than the amount")

    @property
    def change(self) -> Money:
        if self.tendered is None:
            return Money.zero(self.amount.currency)
        return self.tendered - self.amount


@dataclass
class SaleLine:
    line_no: int
    product_id: str
    name: str                      # snapshot (display name, Arabic and English)
    name_ar: str
    unit_price: Money              # snapshot
    quantity: Quantity
    tax_rate: TaxRate              # snapshot
    line_discount: Optional[Discount] = None

    @property
    def gross(self) -> Money:
        q = self.quantity.value
        # unit_price * qty in dirhams, half-up at line level (qty has <= 3 decimals)
        milli = int(q * 1000)
        return Money(round_half_up_div(self.unit_price.amount * milli, 1000), self.unit_price.currency)

    @property
    def discount_amount(self) -> Money:
        if self.line_discount is None:
            return Money.zero(self.unit_price.currency)
        return self.line_discount.amount_for(self.gross)

    @property
    def net(self) -> Money:
        return self.gross - self.discount_amount


@dataclass(frozen=True)
class LineTotals:
    line_no: int
    gross: Money
    line_discount: Money
    cart_discount_share: Money
    tax: Money
    total: Money


@dataclass(frozen=True)
class SaleTotals:
    subtotal: Money
    discount_total: Money
    tax_total: Money
    total: Money
    lines: tuple[LineTotals, ...]


@dataclass
class Sale:
    id: str
    shift_id: str
    cashier_id: str
    created_at: datetime
    number: Optional[int] = None
    customer_id: Optional[str] = None
    lines: list[SaleLine] = field(default_factory=list)
    cart_discount: Optional[Discount] = None
    payments: list[Payment] = field(default_factory=list)
    status: SaleStatus = SaleStatus.DRAFT
    completed_at: Optional[datetime] = None
    currency: str = "LYD"

    # ---- guards -------------------------------------------------------
    def _require_draft(self) -> None:
        if self.status != SaleStatus.DRAFT:
            raise SaleNotEditable(f"sale is {self.status.value}")

    def _line(self, line_no: int) -> SaleLine:
        for line in self.lines:
            if line.line_no == line_no:
                return line
        raise InvalidEntity(f"no line {line_no}")

    # ---- cart editing -------------------------------------------------
    def add_item(self, product: Product, qty: Quantity) -> SaleLine:
        self._require_draft()
        if not product.is_active:
            raise ProductInactive(product.sku)
        if qty.unit != product.unit:
            raise InvalidQuantity("unit mismatch")
        for line in self.lines:
            if line.product_id == product.id:
                line.quantity = line.quantity + qty
                return line
        line = SaleLine(
            line_no=max((l.line_no for l in self.lines), default=0) + 1,
            product_id=product.id, name=product.name_en or product.name_ar,
            name_ar=product.name_ar or product.name_en, unit_price=product.price,
            quantity=qty, tax_rate=product.tax_rate)
        self.lines.append(line)
        return line

    def set_quantity(self, line_no: int, qty: Quantity) -> None:
        self._require_draft()
        line = self._line(line_no)
        if qty.unit != line.quantity.unit:
            raise InvalidQuantity("unit mismatch")
        line.quantity = qty
        if line.line_discount is not None:
            line.line_discount.amount_for(line.gross)  # still valid?

    def remove_line(self, line_no: int) -> None:
        self._require_draft()
        self.lines.remove(self._line(line_no))

    def apply_line_discount(self, line_no: int, discount: Optional[Discount]) -> None:
        self._require_draft()
        line = self._line(line_no)
        if discount is not None:
            discount.amount_for(line.gross)  # validates <= gross
        line.line_discount = discount

    def apply_cart_discount(self, discount: Optional[Discount]) -> None:
        self._require_draft()
        if discount is not None:
            base = sum((l.net.amount for l in self.lines), 0)
            discount.amount_for(Money(base, self.currency))
        self.cart_discount = discount

    def attach_customer(self, customer_id: Optional[str]) -> None:
        self._require_draft()
        self.customer_id = customer_id

    # ---- totals -------------------------------------------------------
    def totals(self) -> SaleTotals:
        cur = self.currency
        nets = [l.net for l in self.lines]
        base = Money(sum(n.amount for n in nets), cur)
        cart_amount = self.cart_discount.amount_for(base) if self.cart_discount else Money.zero(cur)
        shares = cart_amount.allocate([n.amount for n in nets]) if nets else []
        out, subtotal, discounts, tax_total, total = [], Money.zero(cur), Money.zero(cur), Money.zero(cur), Money.zero(cur)
        for line, share in zip(self.lines, shares):
            net_after = line.net - share
            tax = line.tax_rate.tax_on(net_after)
            line_total = line.tax_rate.payable(net_after)
            out.append(LineTotals(line.line_no, line.gross, line.discount_amount, share, tax, line_total))
            subtotal += line.gross
            discounts += line.discount_amount + share
            tax_total += tax
            total += line_total
        return SaleTotals(subtotal, discounts, tax_total, total, tuple(out))

    @property
    def total(self) -> Money:
        return self.totals().total

    # ---- payments -----------------------------------------------------
    @property
    def paid(self) -> Money:
        return Money(sum(p.amount.amount for p in self.payments), self.currency)

    @property
    def balance_due(self) -> Money:
        due = self.total - self.paid
        return due if due.amount > 0 else Money.zero(self.currency)

    @property
    def change_due(self) -> Money:
        return Money(sum(p.change.amount for p in self.payments), self.currency)

    def add_payment(self, payment: Payment) -> None:
        self._require_draft()
        self.payments.append(payment)

    # ---- lifecycle ----------------------------------------------------
    def park(self) -> None:
        self._require_draft()
        if not self.lines:
            raise InvalidEntity("cannot park an empty sale")
        self.status = SaleStatus.PARKED

    def recall(self) -> None:
        if self.status != SaleStatus.PARKED:
            raise SaleNotEditable("sale is not parked")
        self.status = SaleStatus.DRAFT

    def void(self) -> None:
        if self.status not in (SaleStatus.DRAFT, SaleStatus.PARKED):
            raise SaleNotEditable(f"sale is {self.status.value}")
        self.status = SaleStatus.VOIDED

    def complete(self, now: datetime) -> None:
        self._require_draft()
        if not self.lines:
            raise InvalidEntity("cannot complete an empty sale")
        if self.paid < self.total:
            raise InsufficientPayment(f"paid {self.paid.amount} < total {self.total.amount}")
        self.status = SaleStatus.COMPLETED
        self.completed_at = now
