"""Tk shell: login, navigation, idle auto-lock, language switch, status bar."""
from __future__ import annotations

import logging
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Callable, Optional

from ..adapters.controllers import (AdminController, AuthController, CatalogueController, CheckoutController,
                                    RefundController, ReportController, Session, ShiftController)
from ..application.permissions import Permission
from .screens.admin import AdminScreen
from .screens.catalogue import CatalogueScreen
from .screens.checkout import CheckoutScreen
from .screens.refund import RefundScreen
from .screens.reports import ReportsScreen
from .screens.shift import ShiftScreen
from .screens.stock import StockScreen
from .widgets import Dialog, FormRow, Rtl, style_app

log = logging.getLogger(__name__)


@dataclass
class Controllers:
    auth: AuthController
    checkout: CheckoutController
    refund: RefundController
    shift: ShiftController
    catalogue: CatalogueController
    report: ReportController
    admin: AdminController


NAV = [
    ("checkout", "nav.checkout", Permission.SELL, CheckoutScreen),
    ("refund", "nav.refund", Permission.REFUND_REQUEST, RefundScreen),
    ("shift", "nav.shift", Permission.SHIFT, ShiftScreen),
    ("catalogue", "nav.catalogue", Permission.CATALOGUE, CatalogueScreen),
    ("stock", "nav.stock", Permission.STOCK, StockScreen),
    ("reports", "nav.reports", Permission.REPORTS, ReportsScreen),
    ("admin", "nav.admin", Permission.ADMIN, AdminScreen),
]


class App:
    def __init__(self, root: tk.Tk, session: Session, controllers: Controllers,
                 backup_tick: Optional[Callable[[], None]] = None, backup_hours: float = 0):
        self.root, self.session, self.c = root, session, controllers
        self._backup_tick, self._backup_hours = backup_tick, backup_hours
        self.last_activity = time.monotonic()
        self.locked = False
        self.current_key = "checkout"
        self.screen: Optional[ttk.Frame] = None
        root.title("SouqPOS")
        root.geometry("1180x720")
        root.minsize(980, 620)
        style_app(root)
        for ev in ("<Key>", "<Button>", "<Motion>"):
            root.bind_all(ev, self._touch, add="+")
        root.report_callback_exception = self._on_tk_error
        self.container = ttk.Frame(root)
        self.container.pack(fill=tk.BOTH, expand=True)
        self.status_var = tk.StringVar()
        self.status_label: Optional[ttk.Label] = None
        self.show_login()
        root.after(15_000, self._idle_check)
        if backup_tick and backup_hours > 0:
            root.after(int(backup_hours * 3_600_000), self._scheduled_backup)

    # ---- helpers used by screens ---------------------------------------------
    @property
    def p(self):
        return self.session.presenter

    @property
    def rtl(self) -> Rtl:
        return Rtl(self.p.locale == "ar")

    def t(self, key: str, **kw) -> str:
        return self.p.t(key, **kw)

    def notify(self, text: str, error: bool = False) -> None:
        self.status_var.set(text)
        if self.status_label is not None:
            self.status_label.configure(style="Err.TLabel" if error else "Ok.TLabel")
        if error:
            self.root.bell()

    def report(self, outcome, modal: bool = False) -> bool:
        """True when ok. Errors go to the status bar (fast flows) or a dialog (modal=True)."""
        if outcome.ok:
            if outcome.message:
                self.notify(outcome.message)
            return True
        if modal:
            messagebox.showerror(self.t("app.error"), outcome.error, parent=self.root)
        self.notify(outcome.error, error=True)
        return False

    def prompt_approver(self, parent=None) -> Optional[tuple[str, str]]:
        dlg = Dialog(parent or self.root, self.t("approval.title"), self.rtl)
        ttk.Label(dlg.body, text=self.t("approval.hint"), wraplength=320, justify=self.rtl.justify).pack(pady=(0, 8))
        user = FormRow.entry(dlg.body, self.rtl, self.t("login.username"))
        secret = FormRow.entry(dlg.body, self.rtl, self.t("login.secret"), show="*")
        dlg.after(50, user.focus_set)
        dlg.buttons(self.t("ok"), self.t("cancel"),
                    lambda: dlg.close((user.var.get(), secret.var.get())))      # type: ignore[attr-defined]
        return dlg.show()

    # ---- activity / lock ------------------------------------------------------
    def _touch(self, _event=None) -> None:
        self.last_activity = time.monotonic()

    def _idle_check(self) -> None:
        try:
            if self.session.user and not self.locked:
                if time.monotonic() - self.last_activity > self.c.auth.idle_minutes() * 60:
                    self.lock()
        finally:
            self.root.after(15_000, self._idle_check)

    def _scheduled_backup(self) -> None:
        try:
            if self._backup_tick:
                self._backup_tick()
        except Exception:                       # noqa: BLE001 - a failed backup must not crash the till
            log.exception("scheduled backup failed")
        self.root.after(int(self._backup_hours * 3_600_000), self._scheduled_backup)

    def _on_tk_error(self, exc, val, tb) -> None:
        log.error("UI error", exc_info=(exc, val, tb))
        self.notify(self.t("err.Unexpected"), error=True)

    def lock(self) -> None:
        if self.locked or not self.session.user:
            return
        self.locked = True
        self.c.auth.lock()
        while True:
            dlg = Dialog(self.root, self.t("lock.title"), self.rtl)
            ttk.Label(dlg.body, text=self.t("lock.hint", user=self.session.user.display_name)).pack(pady=(0, 8))
            secret = FormRow.entry(dlg.body, self.rtl, self.t("login.secret"), show="*")
            msg = ttk.Label(dlg.body, style="Err.TLabel")
            msg.pack()
            dlg.after(50, secret.focus_set)
            bar = ttk.Frame(dlg.body)
            bar.pack(fill=tk.X, pady=(8, 0))
            ttk.Button(bar, text=self.t("lock.unlock"),
                       command=lambda: dlg.close(("unlock", secret.var.get()))).pack(side=self.rtl.start, padx=4)  # type: ignore[attr-defined]
            ttk.Button(bar, text=self.t("nav.logout"), command=lambda: dlg.close(("logout", ""))).pack(side=self.rtl.start)
            dlg.bind("<Return>", lambda _e: dlg.close(("unlock", secret.var.get())))                              # type: ignore[attr-defined]
            dlg.bind("<Escape>", lambda _e: None)
            dlg.protocol("WM_DELETE_WINDOW", lambda: None)
            action = dlg.show()
            if action and action[0] == "unlock":
                out = self.c.auth.unlock(action[1])
                if out.ok:
                    break
                self.notify(out.error, error=True)
                continue
            if action and action[0] == "logout":
                self.locked = False
                self.logout()
                return
        self.locked = False
        self._touch()

    # ---- screens --------------------------------------------------------------
    def _clear(self) -> None:
        for w in self.container.winfo_children():
            w.destroy()
        self.screen = None
        self.status_label = None

    def show_login(self) -> None:
        self._clear()
        rtl = self.rtl
        self.root.title("SouqPOS")
        frame = ttk.Frame(self.container, padding=30)
        frame.place(relx=0.5, rely=0.4, anchor="center")
        ttk.Label(frame, text="SouqPOS", font=("Segoe UI", 28, "bold")).pack(pady=(0, 4))
        ttk.Label(frame, text=self.t("login.title")).pack(pady=(0, 14))
        user = FormRow.entry(frame, rtl, self.t("login.username"))
        secret = FormRow.entry(frame, rtl, self.t("login.secret"), show="*")
        msg = ttk.Label(frame, style="Err.TLabel", wraplength=320)
        msg.pack(pady=6)

        def do_login(_e=None):
            out = self.c.auth.login(user.var.get(), secret.var.get())            # type: ignore[attr-defined]
            if out.ok:
                self.build_shell()
            else:
                msg.configure(text=out.error)
                secret.var.set("")                                                # type: ignore[attr-defined]
                secret.focus_set()

        ttk.Button(frame, text=self.t("login.button"), style="Big.TButton", command=do_login).pack(fill=tk.X)
        ttk.Button(frame, text="English / العربية", command=self._toggle_login_locale).pack(pady=(12, 0))
        user.focus_set()
        self.root.bind("<Return>", do_login)

    def _toggle_login_locale(self) -> None:
        self.session.set_locale("en" if self.p.locale == "ar" else "ar")
        self.show_login()

    def build_shell(self) -> None:
        self._clear()
        self.root.unbind("<Return>")
        rtl, user = self.rtl, self.session.user
        bar = ttk.Frame(self.container, padding=(8, 6))
        bar.pack(fill=tk.X)
        ttk.Label(bar, text=self.p.user_label(user), font=("Segoe UI", 11, "bold")).pack(side=rtl.start)
        self.shift_label = ttk.Label(bar, text="")
        self.shift_label.pack(side=rtl.start, padx=20)
        ttk.Button(bar, text=self.t("nav.logout"), command=self.logout).pack(side=rtl.end, padx=3)
        ttk.Button(bar, text=self.t("nav.lock"), command=self.lock).pack(side=rtl.end, padx=3)
        ttk.Button(bar, text="English / العربية", command=self.toggle_locale).pack(side=rtl.end, padx=3)
        ttk.Separator(self.container).pack(fill=tk.X)
        status = ttk.Frame(self.container, padding=(8, 3))
        status.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_label = ttk.Label(status, textvariable=self.status_var, style="Ok.TLabel", anchor=rtl.anchor)
        self.status_label.pack(fill=tk.X)
        body = ttk.Frame(self.container)
        body.pack(fill=tk.BOTH, expand=True)
        nav = ttk.Frame(body, padding=6)
        nav.pack(side=rtl.start, fill=tk.Y)
        self.content = ttk.Frame(body, padding=8)
        self.content.pack(side=rtl.start, fill=tk.BOTH, expand=True)
        self.nav_buttons = {}
        for key, label_key, perm, _cls in NAV:
            if self.session.can(perm):
                b = ttk.Button(nav, text=self.t(label_key), style="Nav.TButton", width=16,
                               command=lambda k=key: self.show(k))
                b.pack(fill=tk.X, pady=2)
                self.nav_buttons[key] = b
        self.show(self.current_key if self.current_key in self.nav_buttons else "checkout")

    def refresh_shift_label(self) -> None:
        out = self.c.shift.current()
        if out.ok and hasattr(self, "shift_label"):
            self.shift_label.configure(text=self.p.shift_text(out.value))

    def show(self, key: str) -> None:
        for w in self.content.winfo_children():
            w.destroy()
        cls = next(c for k, _l, _p, c in NAV if k == key)
        self.current_key = key
        self.screen = cls(self.content, self)
        self.screen.pack(fill=tk.BOTH, expand=True)
        self.refresh_shift_label()
        self.notify("")

    def toggle_locale(self) -> None:
        if self.c.auth.toggle_locale().ok:
            self.build_shell()

    def logout(self) -> None:
        self.c.auth.logout()
        self.c.checkout.new_sale()
        self.current_key = "checkout"
        self.show_login()
