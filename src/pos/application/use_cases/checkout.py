"""UC-03..UC-08: scan, edit cart, discounts, complete, park/recall, reprint."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from ...domain.discount import Discount, DiscountKind
from ...domain.errors import DiscountLimitExceeded, InvalidAmount, InvalidEntity, SaleNotEditable
from ...domain.money import Money
from ...domain.quantity import Quantity
from ...domain.sale import Payment, PaymentMethod, Sale, SaleStatus
from ...domain.entities import Role, StockMovement, MovementType
from ..dto import (ApplyDiscountInput, CartView, CompleteSaleInput, EditCartInput,
                   ParkedSaleView, SaleReceipt, ScanItemInput)
from ..errors import ApprovalRejected, ProductNotFound, SaleNotFound
from ..permissions import Permission
from ..ports import PasswordHasher, ReceiptPrinter
from .common import UowFactory, UseCase, cart_view, resolve_approver
from .receipts import DEFAULT_SETTINGS, build_sale_receipt, has_cash, try_print


class CheckoutUseCases(UseCase):
    def __init__(self, uow_factory: UowFactory, clock, ids, hasher: PasswordHasher, printer: ReceiptPrinter):
        super().__init__(uow_factory, clock, ids)
        self._hasher = hasher
        self._printer = printer

    # UC-03
    def scan_item(self, inp: ScanItemInput) -> CartView:
        with self._uow_factory() as uow:
            self._user(uow, inp.actor_id, Permission.SELL)
            shift = self._open_shift(uow)
            if inp.sale_id:
                sale = self._sale(uow, inp.sale_id)
            else:
                sale = Sale(id=self._ids.new_id(), shift_id=shift.id, cashier_id=inp.actor_id,
                            created_at=self._clock.now())
            code = inp.code.strip()
            product = uow.products.get_by_barcode(code) or uow.products.get_by_sku(code)
            if product is None:
                raise ProductNotFound(code)
            sale.add_item(product, Quantity(Decimal(inp.quantity), product.unit))
            uow.sales.save(sale)
            uow.commit()
            return cart_view(sale)

    def get_cart(self, actor_id: str, sale_id: str) -> CartView:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.SELL)
            return cart_view(self._sale(uow, sale_id))

    # UC-04
    def edit_cart(self, inp: EditCartInput) -> CartView:
        with self._uow_factory() as uow:
            self._user(uow, inp.actor_id, Permission.SELL)
            sale = self._sale(uow, inp.sale_id)
            if inp.action == "SET_QTY":
                line = next((l for l in sale.lines if l.line_no == inp.line_no), None)
                if line is None or inp.quantity is None:
                    raise InvalidEntity("line/quantity required")
                sale.set_quantity(inp.line_no, Quantity(Decimal(inp.quantity), line.quantity.unit))
            elif inp.action == "REMOVE":
                sale.remove_line(inp.line_no)
            elif inp.action == "VOID":
                sale.void()
                self._audit(uow, inp.actor_id, "VOID_SALE", "sale", sale.id, lines=len(sale.lines))
            else:
                raise InvalidEntity(f"unknown action {inp.action}")
            uow.sales.save(sale)
            uow.commit()
            return cart_view(sale)

    # UC-05
    def apply_discount(self, inp: ApplyDiscountInput) -> CartView:
        with self._uow_factory() as uow:
            actor = self._user(uow, inp.actor_id, Permission.SELL)
            sale = self._sale(uow, inp.sale_id)
            discount = Discount(DiscountKind(inp.kind), Decimal(inp.value))
            if inp.target == "LINE":
                line = next((l for l in sale.lines if l.line_no == inp.line_no), None)
                if line is None:
                    raise InvalidEntity("line required")
                target = line.gross
            else:
                target = Money(sum(l.net.amount for l in sale.lines), sale.currency)
            discount.amount_for(target)  # validates (<= target) before any approval prompt
            limit = Decimal(uow.settings.get("discount_limit_cashier", DEFAULT_SETTINGS["discount_limit_cashier"]))
            approver = None
            if actor.role == Role.CASHIER and discount.percent_of(target) > limit:
                if inp.approver_credentials is None:
                    raise DiscountLimitExceeded(f"limit {limit}%")
                approver = resolve_approver(uow, self._hasher, actor, inp.approver_credentials)
            if inp.target == "LINE":
                sale.apply_line_discount(inp.line_no, discount if discount.value > 0 else None)
            else:
                sale.apply_cart_discount(discount if discount.value > 0 else None)
            self._audit(uow, inp.actor_id, "DISCOUNT_APPLIED", "sale", sale.id, target=inp.target,
                        kind=inp.kind, value=str(inp.value), line_no=inp.line_no,
                        approver=approver.id if approver else None)
            uow.sales.save(sale)
            uow.commit()
            return cart_view(sale)

    # UC-06
    def complete_sale(self, inp: CompleteSaleInput) -> SaleReceipt:
        with self._uow_factory() as uow:
            actor = self._user(uow, inp.actor_id, Permission.SELL)
            self._open_shift(uow)
            sale = self._sale(uow, inp.sale_id)
            if sale.status != SaleStatus.DRAFT:
                raise SaleNotEditable(f"sale is {sale.status.value}")
            if inp.customer_id is not None:
                sale.attach_customer(inp.customer_id)
            for p in inp.payments:
                method = PaymentMethod(p.method)
                amount = Money(p.amount)
                remaining = sale.total - sale.paid
                if remaining.amount <= 0:
                    raise InvalidAmount("sale is already fully paid")
                if method == PaymentMethod.CASH:
                    tendered = Money(p.tendered) if p.tendered is not None else amount
                    if amount > remaining:
                        amount = remaining          # the overpayment is change
                    sale.add_payment(Payment(method, amount, tendered))
                else:
                    if amount > remaining:
                        raise InvalidAmount("card payment exceeds the balance")
                    sale.add_payment(Payment(method, amount, None, p.reference))
            sale.complete(self._clock.now())
            sale.number = uow.sales.next_number()
            uow.sales.save(sale)
            for line in sale.lines:
                uow.stock.append(StockMovement(self._ids.new_id(), line.product_id, MovementType.SALE,
                                               -line.quantity.value, sale.id, actor.id, self._clock.now()))
            uow.commit()
            receipt = build_sale_receipt(uow, sale, actor)
            cash = has_cash(sale)
        printed = try_print(self._printer, receipt, cash)
        if printed:
            try:
                with self._uow_factory() as uow:
                    uow.sales.mark_printed(sale.id, True)
                    uow.commit()
            except Exception:  # noqa: BLE001
                pass
        from dataclasses import replace
        return replace(receipt, printed=printed)

    # UC-07
    def park_sale(self, actor_id: str, sale_id: str) -> None:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.SELL)
            sale = self._sale(uow, sale_id)
            sale.park()
            uow.sales.save(sale)
            uow.commit()

    def list_parked(self, actor_id: str) -> list[ParkedSaleView]:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.SELL)
            return [ParkedSaleView(s.id, s.created_at, len(s.lines), s.total.amount)
                    for s in uow.sales.list_parked()]

    def recall_sale(self, actor_id: str, sale_id: str) -> CartView:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.SELL)
            self._open_shift(uow)
            sale = self._sale(uow, sale_id)
            sale.recall()
            uow.sales.save(sale)
            uow.commit()
            return cart_view(sale)

    # UC-08
    def reprint_receipt(self, actor_id: str, receipt_no: int) -> SaleReceipt:
        with self._uow_factory() as uow:
            actor = self._user(uow, actor_id, Permission.SELL)
            sale = uow.sales.find_by_number(receipt_no)
            if sale is None or sale.status != SaleStatus.COMPLETED:
                raise SaleNotFound(str(receipt_no))
            cashier = uow.users.get(sale.cashier_id)
            receipt = build_sale_receipt(uow, sale, cashier)
            self._audit(uow, actor.id, "REPRINT", "sale", sale.id, number=receipt_no)
            uow.commit()
        printed = try_print(self._printer, receipt, False)
        if printed:
            with self._uow_factory() as uow:
                uow.sales.mark_printed(sale.id, True)
                uow.commit()
        from dataclasses import replace
        return replace(receipt, printed=printed)
