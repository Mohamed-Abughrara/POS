"""Input / output DTOs. Money is always int dirhams; times are datetimes."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class ApproverCredentials:
    username: str
    secret: str


# ---- auth ---------------------------------------------------------------
@dataclass(frozen=True)
class UserView:
    id: str
    username: str
    display_name: str
    role: str
    locale: str
    is_active: bool = True


# ---- cart ---------------------------------------------------------------
@dataclass(frozen=True)
class CartLineView:
    line_no: int
    product_id: str
    name: str
    name_ar: str
    quantity: Decimal
    unit_price: int
    line_discount: int
    tax: int
    total: int


@dataclass(frozen=True)
class CartView:
    sale_id: str
    status: str
    lines: list[CartLineView]
    subtotal: int
    discount_total: int
    tax_total: int
    total: int
    paid: int = 0
    balance_due: int = 0
    customer_id: Optional[str] = None


@dataclass(frozen=True)
class ScanItemInput:
    actor_id: str
    sale_id: Optional[str]
    code: str
    quantity: Decimal = Decimal(1)


@dataclass(frozen=True)
class EditCartInput:
    actor_id: str
    sale_id: str
    action: str                      # SET_QTY | REMOVE | VOID
    line_no: Optional[int] = None
    quantity: Optional[Decimal] = None


@dataclass(frozen=True)
class ApplyDiscountInput:
    actor_id: str
    sale_id: str
    target: str                      # LINE | CART
    kind: str                        # PERCENT | FIXED
    value: Decimal
    line_no: Optional[int] = None
    approver_credentials: Optional[ApproverCredentials] = None


@dataclass(frozen=True)
class PaymentInput:
    method: str                      # CASH | CARD
    amount: int
    tendered: Optional[int] = None
    reference: Optional[str] = None


@dataclass(frozen=True)
class CompleteSaleInput:
    actor_id: str
    sale_id: str
    payments: list[PaymentInput]
    customer_id: Optional[str] = None


@dataclass(frozen=True)
class ReceiptLineView:
    name: str
    name_ar: str
    quantity: Decimal
    unit_price: int
    total: int


@dataclass(frozen=True)
class PaymentView:
    method: str
    amount: int
    tendered: Optional[int] = None
    reference: Optional[str] = None


@dataclass(frozen=True)
class SaleReceipt:
    sale_id: str
    number: int
    created_at: datetime
    cashier_name: str
    lines: list[ReceiptLineView]
    subtotal: int
    discount_total: int
    tax_total: int
    total: int
    payments: list[PaymentView]
    change_due: int
    printed: bool = False
    header: list[str] = field(default_factory=list)
    footer: str = ""
    customer_name: Optional[str] = None


@dataclass(frozen=True)
class ParkedSaleView:
    sale_id: str
    created_at: datetime
    lines: int
    total: int


# ---- refunds ------------------------------------------------------------
@dataclass(frozen=True)
class RefundInput:
    actor_id: str
    original_receipt_no: int
    lines: list[tuple[int, Decimal]]
    method: str
    reason: str
    approver_credentials: Optional[ApproverCredentials] = None


@dataclass(frozen=True)
class RefundableLineView:
    line_no: int
    name: str
    name_ar: str
    sold: Decimal
    refunded: Decimal
    remaining: Decimal
    unit_total: int


@dataclass(frozen=True)
class RefundableSaleView:
    sale_id: str
    number: int
    created_at: datetime
    total: int
    lines: list[RefundableLineView]


@dataclass(frozen=True)
class RefundReceipt:
    refund_id: str
    number: int
    original_no: int
    created_at: datetime
    lines: list[ReceiptLineView]
    amount: int
    method: str
    reason: str
    printed: bool = False
    header: list[str] = field(default_factory=list)
    footer: str = ""


# ---- shifts -------------------------------------------------------------
@dataclass(frozen=True)
class OpenShiftInput:
    cashier_id: str
    opening_float: int


@dataclass(frozen=True)
class ShiftView:
    shift_id: str
    opened_at: datetime
    opening_float: int
    cashier_id: str = ""


@dataclass(frozen=True)
class CloseShiftInput:
    actor_id: str
    shift_id: str
    counted_cash: int
    denominations: Optional[dict[int, int]] = None
    approver_credentials: Optional[ApproverCredentials] = None
    force_void_parked: bool = False


@dataclass(frozen=True)
class ShiftTotals:
    sales_count: int = 0
    gross: int = 0
    discounts: int = 0
    tax: int = 0
    refunds: int = 0
    cash_sales: int = 0
    cash_refunds: int = 0
    by_method: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ZReport:
    shift_id: str
    opened_at: datetime
    closed_at: datetime
    cashier_name: str
    sales_count: int
    gross: int
    discounts: int
    tax: int
    refunds: int
    net: int
    by_method: dict[str, int]
    opening_float: int
    expected_cash: int
    counted_cash: int
    variance: int
    printed: bool = False
    header: list[str] = field(default_factory=list)
    footer: str = ""


# ---- catalogue / stock ----------------------------------------------------
@dataclass(frozen=True)
class CategoryView:
    id: str
    name_ar: str
    name_en: str
    tax_bp: int = 0
    tax_inclusive: bool = False


@dataclass(frozen=True)
class ProductView:
    id: Optional[str]
    sku: str
    barcode: Optional[str]
    name_ar: str
    name_en: str
    category_id: Optional[str]
    price: int
    cost: int = 0
    unit: str = "PIECE"
    reorder_level: Decimal = Decimal(0)
    is_active: bool = True
    on_hand: Optional[Decimal] = None
    tax_bp: int = 0


@dataclass(frozen=True)
class CustomerView:
    id: Optional[str]
    name: str
    phone: Optional[str] = None
    loyalty_id: Optional[str] = None


@dataclass(frozen=True)
class AdjustStockInput:
    actor_id: str
    product_id: str
    type: str                        # RECEIPT | ADJUSTMENT | WASTE
    qty_delta: Decimal
    reason: str = ""


@dataclass(frozen=True)
class StockLevelView:
    product_id: str
    on_hand: Decimal
    below_reorder: bool


# ---- reports ---------------------------------------------------------------
@dataclass(frozen=True)
class ReportInput:
    actor_id: str
    kind: str       # DAILY | BY_PRODUCT | BY_CASHIER | BY_PAYMENT | TAX
    date_from: date
    date_to: date
    cashier_id: Optional[str] = None


@dataclass(frozen=True)
class ReportView:
    title: str
    columns: list[str]
    rows: list[list]
    totals: list


# ---- admin --------------------------------------------------------------------
@dataclass(frozen=True)
class UserInput:
    id: Optional[str]
    username: str
    display_name: str
    role: str
    locale: str = "en"
    is_active: bool = True
    password: Optional[str] = None
    pin: Optional[str] = None


@dataclass(frozen=True)
class BackupInfo:
    path: str
    size_bytes: int
    created_at: datetime
