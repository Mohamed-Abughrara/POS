"""Builds printable DTOs and prints them without ever failing a committed transaction."""
from __future__ import annotations

import logging
from typing import Any, Optional

from ...domain.entities import Shift, User
from ...domain.refund import Refund
from ...domain.sale import PaymentMethod, Sale
from ..dto import (PaymentView, ReceiptLineView, RefundReceipt, SaleReceipt)
from ..ports import ReceiptPrinter, UnitOfWork

log = logging.getLogger(__name__)

DEFAULT_SETTINGS = {
    "store_name": "SouqPOS Store",
    "store_address": "",
    "store_phone": "",
    "receipt_footer": "Thank you / شكراً لزيارتكم",
    "discount_limit_cashier": "10",     # percent a cashier may apply without approval
    "variance_threshold": "5000",       # dirhams (5 LYD) above which closing needs approval
    "idle_lock_minutes": "5",
}


def header_lines(uow: UnitOfWork) -> list[str]:
    s = uow.settings
    return [x for x in (s.get("store_name", DEFAULT_SETTINGS["store_name"]),
                        s.get("store_address", ""), s.get("store_phone", "")) if x]


def footer_text(uow: UnitOfWork) -> str:
    return uow.settings.get("receipt_footer", DEFAULT_SETTINGS["receipt_footer"])


def build_sale_receipt(uow: UnitOfWork, sale: Sale, cashier: Optional[User], printed: bool = False) -> SaleReceipt:
    t = sale.totals()
    by_no = {lt.line_no: lt for lt in t.lines}
    lines = [ReceiptLineView(l.name, l.name_ar, l.quantity.value, l.unit_price.amount,
                             by_no[l.line_no].total.amount) for l in sale.lines]
    customer = uow.customers.get(sale.customer_id) if sale.customer_id else None
    return SaleReceipt(
        sale_id=sale.id, number=sale.number or 0, created_at=sale.completed_at or sale.created_at,
        cashier_name=cashier.display_name if cashier else "", lines=lines,
        subtotal=t.subtotal.amount, discount_total=t.discount_total.amount,
        tax_total=t.tax_total.amount, total=t.total.amount,
        payments=[PaymentView(p.method.value, p.amount.amount,
                              p.tendered.amount if p.tendered else None, p.reference)
                  for p in sale.payments],
        change_due=sale.change_due.amount, printed=printed, header=header_lines(uow),
        footer=footer_text(uow), customer_name=customer.name if customer else None)


def build_refund_receipt(uow: UnitOfWork, refund: Refund, original_no: int) -> RefundReceipt:
    lines = [ReceiptLineView(l.name, l.name, l.quantity, 0, l.amount.amount) for l in refund.lines]
    return RefundReceipt(refund.id, refund.number or 0, original_no, refund.created_at, lines,
                         refund.amount.amount, refund.method.value, refund.reason,
                         header=header_lines(uow), footer=footer_text(uow))


def try_print(printer: ReceiptPrinter, document: Any, open_drawer: bool) -> bool:
    """Print after commit. A printer failure is logged and reported, never raised (NFR-05)."""
    try:
        printer.print(document)
    except Exception:  # noqa: BLE001 - any driver error must not undo a sale
        log.exception("printing failed")
        return False
    if open_drawer:
        try:
            printer.open_drawer()
        except Exception:  # noqa: BLE001
            log.exception("cash drawer kick failed")
    return True


def has_cash(sale: Sale) -> bool:
    return any(p.method == PaymentMethod.CASH for p in sale.payments)


__all__ = ["DEFAULT_SETTINGS", "build_sale_receipt", "build_refund_receipt", "try_print",
           "has_cash", "header_lines", "footer_text", "Shift"]
