"""Admin screen: users, settings, audit log, backup/restore (UC-14)."""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..widgets import DataTable, FormRow

SETTING_KEYS = ("store_name", "store_address", "store_phone", "receipt_footer", "discount_limit_cashier",
                "variance_threshold", "idle_lock_minutes")


class AdminScreen(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.c = app, app.c.admin
        self.rtl, self.t = app.rtl, app.t
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True)
        for builder, key in ((self._users_tab, "admin.users"), (self._settings_tab, "admin.settings"),
                             (self._audit_tab, "admin.audit"), (self._backup_tab, "admin.backup")):
            tab = ttk.Frame(nb, padding=8)
            nb.add(tab, text=self.t(key))
            builder(tab)

    # ---- users ---------------------------------------------------------------------
    def _users_tab(self, tab) -> None:
        rtl, t = self.rtl, self.t
        self.utable = DataTable(tab, rtl, [("u", t("login.username"), 120), ("n", t("col.name"), 160), ("r", t("admin.role"), 90),
                                           ("a", t("col.active"), 60)], height=12, on_select=self.pick_user)
        self.utable.pack(side=rtl.start, fill=tk.BOTH, expand=True)
        form = ttk.Frame(tab, padding=(12, 0))
        form.pack(side=rtl.start, fill=tk.Y)
        self.uid = None
        self.uf = {k: FormRow.entry(form, rtl, t(lbl), show="*" if k in ("password", "pin") else "", width=22) for k, lbl in (
            ("username", "login.username"), ("display", "col.name"), ("password", "admin.password"), ("pin", "admin.pin"))}
        self.role, self.locale, self.active = tk.StringVar(value="CASHIER"), tk.StringVar(value="en"), tk.BooleanVar(value=True)
        for var, label, values in ((self.role, "admin.role", ("CASHIER", "MANAGER", "ADMIN")), (self.locale, "admin.locale", ("en", "ar"))):
            row = ttk.Frame(form)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=t(label), width=18, anchor=rtl.anchor).pack(side=rtl.start)
            ttk.Combobox(row, textvariable=var, values=values, width=12, state="readonly").pack(side=rtl.start)
        ttk.Checkbutton(form, text=t("col.active"), variable=self.active).pack(anchor=rtl.anchor)
        ttk.Label(form, text=t("admin.password_hint"), wraplength=260, justify=rtl.justify).pack(pady=4)
        ttk.Button(form, text=t("save"), command=self.save_user).pack(anchor=rtl.anchor, pady=4)
        ttk.Button(form, text=t("cat.new"), command=self._reset_user).pack(anchor=rtl.anchor)
        self.load_users()

    def load_users(self) -> None:
        out = self.c.users()
        self.users = {u.id: u for u in out.value} if out.ok else {}
        self.utable.set_rows([(u.username, u.display_name, self.t("role." + u.role), self.t("yes") if u.is_active else self.t("no"))
                              for u in self.users.values()], list(self.users))

    def _reset_user(self) -> None:
        self.uid = None
        for e in self.uf.values():
            e.var.set("")                                                            # type: ignore[attr-defined]
        self.active.set(True)

    def pick_user(self) -> None:
        iid = self.utable.selected()
        u = self.users.get(iid) if iid else None
        if u:
            self.uid = u.id
            self.uf["username"].var.set(u.username)                                  # type: ignore[attr-defined]
            self.uf["display"].var.set(u.display_name)                               # type: ignore[attr-defined]
            self.uf["password"].var.set("")                                          # type: ignore[attr-defined]
            self.uf["pin"].var.set("")                                               # type: ignore[attr-defined]
            self.role.set(u.role)
            self.locale.set(u.locale)
            self.active.set(u.is_active)

    def save_user(self) -> None:
        g = {k: e.var.get() for k, e in self.uf.items()}                             # type: ignore[attr-defined]
        out = self.c.save_user(self.uid, g["username"], g["display"], self.role.get(), self.locale.get(),
                               self.active.get(), g["password"], g["pin"])
        if self.app.report(out, modal=not out.ok):
            self.uid = out.value.id
            self.load_users()

    # ---- settings -------------------------------------------------------------------
    def _settings_tab(self, tab) -> None:
        out = self.c.settings()
        values = out.value if out.ok else {}
        self.sf = {}
        for key in SETTING_KEYS:
            e = FormRow.entry(tab, self.rtl, self.t("setting." + key), width=40)
            e.var.set(values.get(key, ""))                                           # type: ignore[attr-defined]
            self.sf[key] = e
        ttk.Label(tab, text=self.t("setting.hint"), wraplength=520, justify=self.rtl.justify).pack(pady=6, anchor=self.rtl.anchor)
        ttk.Button(tab, text=self.t("save"), command=self.save_settings).pack(anchor=self.rtl.anchor)

    def save_settings(self) -> None:
        self.app.report(self.c.save_settings({k: e.var.get() for k, e in self.sf.items()}), modal=True)   # type: ignore[attr-defined]

    # ---- audit ----------------------------------------------------------------------
    def _audit_tab(self, tab) -> None:
        t = self.t
        self.atable = DataTable(tab, self.rtl, [("at", t("col.time"), 130), ("u", t("login.username"), 90), ("a", t("audit.action"), 150),
                                                ("e", t("audit.entity"), 80), ("d", t("audit.details"), 360)], height=18)
        self.atable.pack(fill=tk.BOTH, expand=True)
        ttk.Button(tab, text=t("report.run"), command=self.load_audit).pack(pady=6, anchor=self.rtl.anchor)
        self.load_audit()

    def load_audit(self) -> None:
        out = self.c.audit()
        if self.app.report(out):
            self.atable.set_rows(out.value)

    # ---- backup ---------------------------------------------------------------------
    def _backup_tab(self, tab) -> None:
        t, rtl = self.t, self.rtl
        bar = ttk.Frame(tab)
        bar.pack(fill=tk.X)
        ttk.Button(bar, text=t("backup.now"), command=self.backup_now).pack(side=rtl.start, padx=4)
        ttk.Button(bar, text=t("backup.restore_selected"), command=self.restore_selected).pack(side=rtl.start, padx=4)
        ttk.Button(bar, text=t("backup.restore_file"), command=self.restore_file).pack(side=rtl.start, padx=4)
        self.btable = DataTable(tab, rtl, [("p", t("backup.file"), 420), ("t", t("col.time"), 130), ("s", t("backup.size"), 80)], height=14)
        self.btable.pack(fill=tk.BOTH, expand=True, pady=8)
        self.load_backups()

    def load_backups(self) -> None:
        out = self.c.backups()
        if self.app.report(out):
            self.btable.set_rows(out.value, [r[0] for r in out.value])

    def backup_now(self) -> None:
        if self.app.report(self.c.backup_now(), modal=False):
            self.load_backups()

    def _restore(self, path: str) -> None:
        if not messagebox.askyesno(self.t("app.confirm"), self.t("backup.confirm_restore"), parent=self):
            return
        if self.app.report(self.c.restore(path), modal=True):
            self.app.logout()

    def restore_selected(self) -> None:
        iid = self.btable.selected()
        if iid:
            self._restore(iid)

    def restore_file(self) -> None:
        path = filedialog.askopenfilename(parent=self, filetypes=[("SQLite", "*.db"), ("*", "*.*")])
        if path:
            self._restore(path)
