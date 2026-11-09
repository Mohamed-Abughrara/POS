"""Simple entities: Category, Product, Customer, User, Shift, StockMovement, AuditEntry."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from .barcode import Barcode
from .errors import (InvalidAmount, InvalidEntity, ShiftNotOpen)
from .money import Money
from .quantity import Unit
from .tax import TaxRate


@dataclass
class Category:
    id: str
    name_ar: str
    name_en: str
    tax_rate: TaxRate = field(default_factory=TaxRate)


@dataclass
class Product:
    id: str
    sku: str
    name_ar: str
    name_en: str
    price: Money
    category_id: Optional[str] = None
    barcode: Optional[str] = None
    cost: Money = field(default_factory=Money.zero)
    unit: Unit = Unit.PIECE
    reorder_level: Decimal = Decimal(0)
    is_active: bool = True
    tax_rate: TaxRate = field(default_factory=TaxRate)  # resolved from the category on load

    def __post_init__(self):
        if self.price.amount < 0 or self.cost.amount < 0:
            raise InvalidAmount("price and cost must be >= 0")
        if not self.sku.strip():
            raise InvalidEntity("sku required")
        if not (self.name_ar.strip() or self.name_en.strip()):
            raise InvalidEntity("product name required")
        if self.barcode:
            self.barcode = Barcode(self.barcode).value
        else:
            self.barcode = None

    def name(self, locale: str = "en") -> str:
        primary, other = (self.name_ar, self.name_en) if locale == "ar" else (self.name_en, self.name_ar)
        return primary or other


@dataclass
class Customer:
    id: str
    name: str
    phone: Optional[str] = None
    loyalty_id: Optional[str] = None

    def __post_init__(self):
        if not self.name.strip():
            raise InvalidEntity("customer name required")


class Role(str, Enum):
    CASHIER = "CASHIER"
    MANAGER = "MANAGER"
    ADMIN = "ADMIN"

    @property
    def rank(self) -> int:
        return {"CASHIER": 1, "MANAGER": 2, "ADMIN": 3}[self.value]

    def at_least(self, other: "Role") -> bool:
        return self.rank >= other.rank


@dataclass
class User:
    id: str
    username: str
    display_name: str
    role: Role
    password_hash: str
    pin_hash: Optional[str] = None
    is_active: bool = True
    locale: str = "en"

    def __post_init__(self):
        if not self.username.strip():
            raise InvalidEntity("username required")
        if self.locale not in ("ar", "en"):
            raise InvalidEntity("locale must be ar or en")


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass
class Shift:
    id: str
    cashier_id: str
    opened_at: datetime
    opening_float: Money
    status: ShiftStatus = ShiftStatus.OPEN
    closed_at: Optional[datetime] = None
    counted_cash: Optional[Money] = None
    expected_cash: Optional[Money] = None

    def __post_init__(self):
        if self.opening_float.amount < 0:
            raise InvalidAmount("opening float must be >= 0")

    @property
    def is_open(self) -> bool:
        return self.status == ShiftStatus.OPEN

    @property
    def variance(self) -> Optional[Money]:
        if self.counted_cash is None or self.expected_cash is None:
            return None
        return self.counted_cash - self.expected_cash

    def close(self, counted: Money, expected: Money, now: datetime) -> None:
        if not self.is_open:
            raise ShiftNotOpen("shift already closed")
        if counted.amount < 0:
            raise InvalidAmount("counted cash must be >= 0")
        self.counted_cash, self.expected_cash = counted, expected
        self.closed_at, self.status = now, ShiftStatus.CLOSED


class MovementType(str, Enum):
    SALE = "SALE"
    REFUND = "REFUND"
    RECEIPT = "RECEIPT"
    ADJUSTMENT = "ADJUSTMENT"
    WASTE = "WASTE"


@dataclass(frozen=True)
class StockMovement:
    id: str
    product_id: str
    type: MovementType
    qty_delta: Decimal
    ref_id: Optional[str]
    user_id: str
    at: datetime
    reason: str = ""


@dataclass(frozen=True)
class AuditEntry:
    id: str
    at: datetime
    user_id: Optional[str]
    action: str
    entity: str
    entity_id: Optional[str]
    details: dict = field(default_factory=dict)
