"""UC-14 Administer (users, settings, backup/restore) and first-run seeding."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...domain.entities import Category, Role, User
from ..dto import BackupInfo, UserInput, UserView
from ..errors import DuplicateEntity, InvalidInput, UserNotFound
from ..permissions import Permission
from ..ports import BackupService, PasswordHasher
from .auth import to_user_view
from .common import UowFactory, UseCase
from .receipts import DEFAULT_SETTINGS

MIN_PASSWORD = 6


class AdminUseCases(UseCase):
    def __init__(self, uow_factory: UowFactory, clock, ids, hasher: PasswordHasher, backup: BackupService):
        super().__init__(uow_factory, clock, ids)
        self._hasher = hasher
        self._backup = backup

    # ---- users ---------------------------------------------------------------
    def list_users(self, actor_id: str) -> list[UserView]:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.ADMIN)
            return [to_user_view(u) for u in uow.users.list()]

    def save_user(self, actor_id: str, inp: UserInput) -> UserView:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.ADMIN)
            existing = uow.users.get(inp.id) if inp.id else None
            if inp.id and existing is None:
                raise UserNotFound(inp.id)
            clash = uow.users.get_by_username(inp.username.strip())
            if clash and clash.id != (existing.id if existing else None):
                raise DuplicateEntity(inp.username)
            if existing is None and not inp.password:
                raise InvalidInput("password required for a new user")
            if inp.password is not None and len(inp.password) < MIN_PASSWORD and inp.password != "":
                raise InvalidInput(f"password must be at least {MIN_PASSWORD} characters")
            if inp.pin and not (inp.pin.isdigit() and 4 <= len(inp.pin) <= 8):
                raise InvalidInput("PIN must be 4-8 digits")
            role = Role(inp.role)
            if existing and existing.role == Role.ADMIN and (role != Role.ADMIN or not inp.is_active):
                others = [u for u in uow.users.list() if u.role == Role.ADMIN and u.is_active and u.id != existing.id]
                if not others:
                    raise InvalidInput("cannot remove the last active admin")
            user = User(
                id=existing.id if existing else self._ids.new_id(), username=inp.username.strip(),
                display_name=inp.display_name.strip() or inp.username.strip(), role=role,
                password_hash=self._hasher.hash(inp.password) if inp.password else existing.password_hash,
                pin_hash=self._hasher.hash(inp.pin) if inp.pin else (existing.pin_hash if existing else None),
                is_active=inp.is_active, locale=inp.locale)
            uow.users.save(user)
            self._audit(uow, actor_id, "USER_SAVED" if existing else "USER_CREATED", "user", user.id,
                        role=role.value, active=user.is_active, password_changed=bool(inp.password))
            uow.commit()
            return to_user_view(user)

    def set_locale(self, user_id: str, locale: str) -> None:
        with self._uow_factory() as uow:
            user = self._user(uow, user_id)
            user.locale = locale
            uow.users.save(user)
            uow.commit()

    # ---- settings --------------------------------------------------------------
    def get_settings(self, actor_id: str) -> dict[str, str]:
        with self._uow_factory() as uow:
            self._user(uow, actor_id)  # every role may read (idle lock etc.)
            return {**DEFAULT_SETTINGS, **uow.settings.all()}

    def save_settings(self, actor_id: str, values: dict[str, str]) -> None:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.ADMIN)
            for k, v in values.items():
                uow.settings.set(k, str(v))
            self._audit(uow, actor_id, "SETTINGS_CHANGED", "settings", None, keys=sorted(values))
            uow.commit()

    def recent_audit(self, actor_id: str, limit: int = 200) -> list:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.ADMIN)
            names = {u.id: u.username for u in uow.users.list()}
            return [(e.at, names.get(e.user_id, ""), e.action, e.entity, e.details)
                    for e in uow.audit.recent(limit)]

    # ---- backup ----------------------------------------------------------------
    def backup_now(self, actor_id: Optional[str], destination: Optional[Path] = None) -> BackupInfo:
        with self._uow_factory() as uow:
            if actor_id:
                self._user(uow, actor_id, Permission.ADMIN)
        info = self._backup.create(destination)
        with self._uow_factory() as uow:
            self._audit(uow, actor_id, "BACKUP", "database", None, path=info.path)
            uow.commit()
        return info

    def list_backups(self, actor_id: str) -> list[BackupInfo]:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.ADMIN)
        return self._backup.list()

    def restore(self, actor_id: str, source: Path) -> None:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.ADMIN)
        self._backup.restore(source)
        with self._uow_factory() as uow:   # the restored DB may predate this user: best effort
            if uow.users.get(actor_id):
                self._audit(uow, actor_id, "RESTORE", "database", None, source=str(source))
                uow.commit()


class SeedDefaults(UseCase):
    """First-run data: default admin, default settings and a default category."""

    def __init__(self, uow_factory: UowFactory, clock, ids, hasher: PasswordHasher):
        super().__init__(uow_factory, clock, ids)
        self._hasher = hasher

    def run(self, admin_username: str = "admin", admin_password: str = "admin123") -> bool:
        with self._uow_factory() as uow:
            if uow.users.list():
                return False
            for k, v in DEFAULT_SETTINGS.items():
                uow.settings.set(k, v)
            uow.categories.save(Category(self._ids.new_id(), "عام", "General"))
            admin = User(self._ids.new_id(), admin_username, "Administrator", Role.ADMIN,
                         self._hasher.hash(admin_password), None, True, "en")
            uow.users.save(admin)
            self._audit(uow, admin.id, "SEED", "system", None)
            uow.commit()
            return True
