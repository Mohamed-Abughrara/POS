"""Refund aggregate: a new record linked to a completed sale (sales are never edited)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Mapping, Optional, Sequence

from .errors import InvalidQuantity, RefundExceedsSold, SaleNotRefundable
from .money import Money, round_half_up_div
from .sale import PaymentMethod, Sale, SaleStatus


@dataclass(frozen=True)
class RefundLine:
    line_no: int
    product_id: str
    name: str
    quantity: Decimal
    amount: Money


@dataclass
class Refund:
    id: str
    original_sale_id: str
    shift_id: str
    method: PaymentMethod
    approved_by: str
    reason: str
    created_at: datetime
    lines: list[RefundLine] = field(default_factory=list)
    number: Optional[int] = None

    @property
    def amount(self) -> Money:
        cur = self.lines[0].amount.currency if self.lines else "LYD"
        return Money(sum(l.amount.amount for l in self.lines), cur)

    @staticmethod
    def build(*, id: str, original: Sale, shift_id: str, requested: Sequence[tuple[int, Decimal]],
              already_refunded: Mapping[int, tuple[Decimal, Money]], method: PaymentMethod,
              approved_by: str, reason: str, created_at: datetime) -> "Refund":
        """`already_refunded` maps line_no -> (qty, amount) refunded by earlier refunds."""
        if original.status != SaleStatus.COMPLETED:
            raise SaleNotRefundable("only completed sales can be refunded")
        totals = {t.line_no: t for t in original.totals().lines}
        refund = Refund(id=id, original_sale_id=original.id, shift_id=shift_id, method=method,
                        approved_by=approved_by, reason=reason, created_at=created_at)
        seen: set[int] = set()
        for line_no, qty in requested:
            qty = Decimal(qty)
            if qty <= 0:
                raise InvalidQuantity("refund quantity must be > 0")
            if line_no in seen:
                raise InvalidQuantity("duplicate line in refund")
            seen.add(line_no)
            line = next((l for l in original.lines if l.line_no == line_no), None)
            if line is None:
                raise SaleNotRefundable(f"no line {line_no} on the original sale")
            prev_qty, prev_amount = already_refunded.get(line_no, (Decimal(0), Money.zero(original.currency)))
            remaining = line.quantity.value - prev_qty
            if qty > remaining:
                raise RefundExceedsSold(f"line {line_no}: {qty} > {remaining}")
            line_total = totals[line_no].total
            if qty == remaining:
                amount = line_total - prev_amount          # absorb rounding drift on the last refund
            else:
                amount = Money(round_half_up_div(line_total.amount * int(qty * 1000),
                                                 int(line.quantity.value * 1000)), original.currency)
            refund.lines.append(RefundLine(line_no, line.product_id, line.name, qty, amount))
        if not refund.lines:
            raise InvalidQuantity("nothing to refund")
        return refund
