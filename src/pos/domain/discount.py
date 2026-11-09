from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .errors import InvalidDiscount
from .money import Money, round_half_up_div


class DiscountKind(str, Enum):
    PERCENT = "PERCENT"
    FIXED = "FIXED"


@dataclass(frozen=True)
class Discount:
    """PERCENT: value is 0..100 (max 2 decimals). FIXED: value is integer dirhams."""
    kind: DiscountKind
    value: Decimal

    def __post_init__(self):
        v = self.value if isinstance(self.value, Decimal) else Decimal(str(self.value))
        object.__setattr__(self, "value", v)
        if v < 0:
            raise InvalidDiscount("discount must be >= 0")
        if self.kind == DiscountKind.PERCENT:
            if v > 100 or v != v.quantize(Decimal("0.01")):
                raise InvalidDiscount("percent must be 0..100 with at most 2 decimals")
        elif v != v.to_integral_value():
            raise InvalidDiscount("fixed discount must be whole dirhams")

    def amount_for(self, target: Money) -> Money:
        if self.kind == DiscountKind.PERCENT:
            bp = int(self.value * 100)
            return Money(round_half_up_div(target.amount * bp, 10_000), target.currency)
        amount = Money(int(self.value), target.currency)
        if amount > target:
            raise InvalidDiscount("fixed discount exceeds amount")
        return amount

    def percent_of(self, target: Money) -> Decimal:
        if self.kind == DiscountKind.PERCENT:
            return self.value
        if target.amount == 0:
            return Decimal(0)
        return Decimal(int(self.value)) * 100 / Decimal(target.amount)
