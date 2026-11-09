from __future__ import annotations

from dataclasses import dataclass

from .errors import InvalidTaxRate
from .money import Money, round_half_up_div


@dataclass(frozen=True)
class TaxRate:
    basis_points: int = 0
    inclusive: bool = False

    def __post_init__(self):
        if not 0 <= self.basis_points <= 10_000:
            raise InvalidTaxRate("basis points must be 0..10000")

    def tax_on(self, net: Money) -> Money:
        """Tax contained in / added to `net` (the post-discount line amount)."""
        if self.basis_points == 0:
            return Money.zero(net.currency)
        if self.inclusive:
            base = round_half_up_div(net.amount * 10_000, 10_000 + self.basis_points)
            return Money(net.amount - base, net.currency)
        return net.basis_points(self.basis_points)

    def payable(self, net: Money) -> Money:
        """Amount the customer pays for `net` after tax rules."""
        return net if self.inclusive else net + self.tax_on(net)
