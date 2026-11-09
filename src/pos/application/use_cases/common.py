"""Shared helpers for use cases."""
from __future__ import annotations

from decimal import Decimal
from typing import Callable, Optional

from ...domain.entities import AuditEntry, Role, Shift, User
from ...domain.errors import ShiftNotOpen
from ...domain.quantity import Quantity
from ...domain.sale import Sale
from ..dto import ApproverCredentials, CartLineView, CartView
from ..errors import (ApprovalRejected, ApprovalRequired, AuthenticationFailed, SaleNotFound,
                      UserNotFound)
from ..permissions import Permission, require
from ..ports import Clock, IdGenerator, PasswordHasher, UnitOfWork

UowFactory = Callable[[], UnitOfWork]


class UseCase:
    def __init__(self, uow_factory: UowFactory, clock: Clock, ids: IdGenerator):
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids

    def _audit(self, uow: UnitOfWork, user_id: Optional[str], action: str, entity: str,
               entity_id: Optional[str] = None, **details) -> None:
        uow.audit.append(AuditEntry(self._ids.new_id(), self._clock.now(), user_id, action,
                                    entity, entity_id, details))

    @staticmethod
    def _user(uow: UnitOfWork, user_id: str, permission: Optional[Permission] = None) -> User:
        user = uow.users.get(user_id)
        if user is None:
            raise UserNotFound(user_id)
        if permission is not None:
            require(user, permission)
        return user

    @staticmethod
    def _open_shift(uow: UnitOfWork) -> Shift:
        shift = uow.shifts.get_open()
        if shift is None:
            raise ShiftNotOpen("no open shift")
        return shift

    @staticmethod
    def _sale(uow: UnitOfWork, sale_id: str) -> Sale:
        sale = uow.sales.get(sale_id)
        if sale is None:
            raise SaleNotFound(sale_id)
        return sale


def resolve_approver(uow: UnitOfWork, hasher: PasswordHasher, actor: User,
                     credentials: Optional[ApproverCredentials], minimum: Role = Role.MANAGER) -> User:
    """The actor self-approves if they already hold the role; otherwise credentials are verified."""
    if credentials is not None:
        approver = uow.users.get_by_username(credentials.username)
        if (approver is None or not approver.is_active or not approver.role.at_least(minimum)
                or not verify_secret(hasher, approver, credentials.secret)):
            raise ApprovalRejected(credentials.username)
        return approver
    if actor.role.at_least(minimum):
        return actor
    raise ApprovalRequired(minimum.value)


def verify_secret(hasher: PasswordHasher, user: User, secret: str) -> bool:
    if hasher.verify(secret, user.password_hash):
        return True
    return bool(user.pin_hash) and hasher.verify(secret, user.pin_hash)


def authenticate(uow: UnitOfWork, hasher: PasswordHasher, username: str, secret: str) -> User:
    user = uow.users.get_by_username(username)
    if user is None or not user.is_active or not verify_secret(hasher, user, secret):
        raise AuthenticationFailed(username)
    return user


def make_quantity(value: Decimal, unit) -> Quantity:
    return Quantity(Decimal(value), unit)


def cart_view(sale: Sale) -> CartView:
    t = sale.totals()
    by_no = {lt.line_no: lt for lt in t.lines}
    lines = [CartLineView(l.line_no, l.product_id, l.name, l.name_ar, l.quantity.value,
                          l.unit_price.amount, by_no[l.line_no].line_discount.amount
                          + by_no[l.line_no].cart_discount_share.amount,
                          by_no[l.line_no].tax.amount, by_no[l.line_no].total.amount)
             for l in sale.lines]
    return CartView(sale.id, sale.status.value, lines, t.subtotal.amount, t.discount_total.amount,
                    t.tax_total.amount, t.total.amount, sale.paid.amount, sale.balance_due.amount,
                    sale.customer_id)
