"""UC-09 ProcessRefund (+ lookup of the refundable quantities of a receipt)."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from ...domain.entities import MovementType, StockMovement
from ...domain.money import Money
from ...domain.refund import Refund
from ...domain.sale import PaymentMethod, SaleStatus
from ...domain.errors import SaleNotRefundable
from ..dto import RefundableLineView, RefundableSaleView, RefundInput, RefundReceipt
from ..errors import SaleNotFound
from ..permissions import Permission
from ..ports import PasswordHasher, ReceiptPrinter, UnitOfWork
from .common import UowFactory, UseCase, resolve_approver
from .receipts import build_refund_receipt, try_print


def _already_refunded(uow: UnitOfWork, sale_id: str) -> dict[int, tuple[Decimal, Money]]:
    acc: dict[int, tuple[Decimal, Money]] = {}
    for r in uow.refunds.list_for_sale(sale_id):
        for l in r.lines:
            q, a = acc.get(l.line_no, (Decimal(0), Money.zero()))
            acc[l.line_no] = (q + l.quantity, a + l.amount)
    return acc


class RefundUseCases(UseCase):
    def __init__(self, uow_factory: UowFactory, clock, ids, hasher: PasswordHasher, printer: ReceiptPrinter):
        super().__init__(uow_factory, clock, ids)
        self._hasher = hasher
        self._printer = printer

    def lookup(self, actor_id: str, receipt_no: int) -> RefundableSaleView:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.REFUND_REQUEST)
            sale = uow.sales.find_by_number(receipt_no)
            if sale is None:
                raise SaleNotFound(str(receipt_no))
            if sale.status != SaleStatus.COMPLETED:
                raise SaleNotRefundable("only completed sales can be refunded")
            prior = _already_refunded(uow, sale.id)
            totals = {t.line_no: t for t in sale.totals().lines}
            lines = []
            for l in sale.lines:
                done = prior.get(l.line_no, (Decimal(0), Money.zero()))[0]
                unit_total = (totals[l.line_no].total.amount * 1000) // int(l.quantity.value * 1000)
                lines.append(RefundableLineView(l.line_no, l.name, l.name_ar, l.quantity.value, done,
                                                l.quantity.value - done, unit_total))
            return RefundableSaleView(sale.id, receipt_no, sale.created_at, sale.total.amount, lines)

    def process_refund(self, inp: RefundInput) -> RefundReceipt:
        with self._uow_factory() as uow:
            actor = self._user(uow, inp.actor_id, Permission.REFUND_REQUEST)
            shift = self._open_shift(uow)
            original = uow.sales.find_by_number(inp.original_receipt_no)
            if original is None:
                raise SaleNotFound(str(inp.original_receipt_no))
            approver = resolve_approver(uow, self._hasher, actor, inp.approver_credentials)
            method = PaymentMethod(inp.method)
            refund = Refund.build(
                id=self._ids.new_id(), original=original, shift_id=shift.id,
                requested=[(n, Decimal(q)) for n, q in inp.lines],
                already_refunded=_already_refunded(uow, original.id), method=method,
                approved_by=approver.id, reason=inp.reason, created_at=self._clock.now())
            refund.number = uow.refunds.next_number()
            uow.refunds.save(refund)
            for l in refund.lines:
                uow.stock.append(StockMovement(self._ids.new_id(), l.product_id, MovementType.REFUND,
                                               l.quantity, refund.id, actor.id, self._clock.now(),
                                               inp.reason))
            self._audit(uow, actor.id, "REFUND", "refund", refund.id, original=inp.original_receipt_no,
                        amount=refund.amount.amount, method=inp.method, approver=approver.id,
                        reason=inp.reason)
            uow.commit()
            receipt = build_refund_receipt(uow, refund, inp.original_receipt_no)
        printed = try_print(self._printer, receipt, method == PaymentMethod.CASH)
        return replace(receipt, printed=printed)
