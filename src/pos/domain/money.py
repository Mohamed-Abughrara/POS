"""Money value object: integer dirhams (1 LYD = 1,000 dirhams). Never floats."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .errors import CurrencyMismatch, InvalidAmount

DIRHAMS_PER_LYD = 1000


def round_half_up_div(numerator: int, denominator: int) -> int:
    """Integer division rounding half away from zero (half-up for positive amounts)."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    sign = -1 if numerator < 0 else 1
    return sign * ((abs(numerator) * 2 + denominator) // (denominator * 2))


@dataclass(frozen=True)
class Money:
    amount: int
    currency: str = "LYD"

    def __post_init__(self):
        if isinstance(self.amount, bool) or not isinstance(self.amount, int):
            raise InvalidAmount(f"Money amount must be int dirhams, got {type(self.amount).__name__}")

    @classmethod
    def zero(cls, currency: str = "LYD") -> "Money":
        return cls(0, currency)

    def _check(self, other: "Money") -> None:
        if not isinstance(other, Money) or other.currency != self.currency:
            raise CurrencyMismatch(f"{self.currency} vs {getattr(other, 'currency', other)}")

    def __add__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.amount, self.currency)

    def __lt__(self, other: "Money") -> bool:
        self._check(other)
        return self.amount < other.amount

    def __le__(self, other: "Money") -> bool:
        self._check(other)
        return self.amount <= other.amount

    def __gt__(self, other: "Money") -> bool:
        self._check(other)
        return self.amount > other.amount

    def __ge__(self, other: "Money") -> bool:
        self._check(other)
        return self.amount >= other.amount

    def times_ratio(self, numerator: int, denominator: int) -> "Money":
        """amount * numerator / denominator, rounded half-up."""
        return Money(round_half_up_div(self.amount * numerator, denominator), self.currency)

    def basis_points(self, bp: int) -> "Money":
        return self.times_ratio(bp, 10_000)

    def is_zero(self) -> bool:
        return self.amount == 0

    def allocate(self, ratios: Sequence[int]) -> list["Money"]:
        """Split without losing a dirham; remainder goes to the largest shares first."""
        if not ratios or any(r < 0 for r in ratios):
            raise InvalidAmount("ratios must be non-empty and non-negative")
        total = sum(ratios)
        if total == 0:
            return [Money(0, self.currency) for _ in ratios]
        sign = -1 if self.amount < 0 else 1
        absolute = abs(self.amount)
        shares = [absolute * r // total for r in ratios]
        remainder = absolute - sum(shares)
        order = sorted(range(len(ratios)), key=lambda i: (-ratios[i], i))
        for i in order[:remainder]:
            shares[i] += 1
        return [Money(sign * s, self.currency) for s in shares]
