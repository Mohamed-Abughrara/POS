from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .errors import InvalidQuantity


class Unit(str, Enum):
    PIECE = "PIECE"
    KG = "KG"


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    unit: Unit = Unit.PIECE

    def __post_init__(self):
        v = self.value if isinstance(self.value, Decimal) else Decimal(str(self.value))
        object.__setattr__(self, "value", v)
        if v <= 0:
            raise InvalidQuantity("quantity must be > 0")
        if self.unit == Unit.PIECE and v != v.to_integral_value():
            raise InvalidQuantity("pieces must be whole")
        if self.unit == Unit.KG and v != v.quantize(Decimal("0.001")):
            raise InvalidQuantity("KG allows at most 3 decimals")

    def __add__(self, other: "Quantity") -> "Quantity":
        if other.unit != self.unit:
            raise InvalidQuantity("unit mismatch")
        return Quantity(self.value + other.value, self.unit)
