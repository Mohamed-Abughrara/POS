from __future__ import annotations

from enum import Enum

from ..domain.entities import Role, User
from .errors import PermissionDenied


class Permission(str, Enum):
    SELL = "SELL"
    REFUND_REQUEST = "REFUND_REQUEST"
    SHIFT = "SHIFT"
    CATALOGUE = "CATALOGUE"
    STOCK = "STOCK"
    REPORTS = "REPORTS"
    APPROVE = "APPROVE"
    ADMIN = "ADMIN"


_CASHIER = {Permission.SELL, Permission.REFUND_REQUEST, Permission.SHIFT}
_MANAGER = _CASHIER | {Permission.CATALOGUE, Permission.STOCK, Permission.REPORTS, Permission.APPROVE}
_ADMIN = _MANAGER | {Permission.ADMIN}

ROLE_PERMISSIONS = {Role.CASHIER: _CASHIER, Role.MANAGER: _MANAGER, Role.ADMIN: _ADMIN}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]


def require(user: User, permission: Permission) -> None:
    if not user.is_active or not has_permission(user.role, permission):
        raise PermissionDenied(permission.value)
