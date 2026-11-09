"""UC-01 Login / Lock / Unlock."""
from __future__ import annotations

from ..dto import UserView
from ..errors import AuthenticationFailed
from ..ports import PasswordHasher
from .common import UowFactory, UseCase, authenticate, verify_secret
from ...domain.entities import User


def to_user_view(u: User) -> UserView:
    return UserView(u.id, u.username, u.display_name, u.role.value, u.locale, u.is_active)


class AuthUseCases(UseCase):
    def __init__(self, uow_factory: UowFactory, clock, ids, hasher: PasswordHasher):
        super().__init__(uow_factory, clock, ids)
        self._hasher = hasher

    def login(self, username: str, secret: str) -> UserView:
        with self._uow_factory() as uow:
            try:
                user = authenticate(uow, self._hasher, username, secret)
            except AuthenticationFailed:
                self._audit(uow, None, "LOGIN_FAILED", "user", None, username=username)
                uow.commit()
                raise
            self._audit(uow, user.id, "LOGIN", "user", user.id)
            uow.commit()
            return to_user_view(user)

    def lock(self, user_id: str) -> None:
        with self._uow_factory() as uow:
            self._audit(uow, user_id, "LOCK", "user", user_id)
            uow.commit()

    def unlock(self, user_id: str, secret: str) -> UserView:
        with self._uow_factory() as uow:
            user = self._user(uow, user_id)
            if not user.is_active or not verify_secret(self._hasher, user, secret):
                self._audit(uow, user_id, "UNLOCK_FAILED", "user", user_id)
                uow.commit()
                raise AuthenticationFailed(user.username)
            self._audit(uow, user_id, "UNLOCK", "user", user_id)
            uow.commit()
            return to_user_view(user)
