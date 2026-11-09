"""Shift screen: open with float, close with cash count and Z-report (UC-02, UC-12)."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ..widgets import DataTable, FormRow


class ShiftScreen(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.c = app, app.c.shift
        self.rtl, self.t = app.rtl, app.t
        self.shift = None
        self.body = ttk.Frame(self)
        self.body.pack(fill=tk.BOTH, expand=True)
        self.refresh()

    def refresh(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        out = self.c.current()
        if not self.app.report(out):
            return
        self.shift = out.value
        rtl, t = self.rtl, self.t
        ttk.Label(self.body, text=self.app.p.shift_text(self.shift), font=("Segoe UI", 14, "bold")).pack(anchor=rtl.anchor, pady=8)
        if self.shift is None:
            self.amount = FormRow.entry(self.body, rtl, t("shift.opening_float"))
            self.amount.var.set("0")                                              # type: ignore[attr-defined]
            self.amount.focus_set()
            ttk.Button(self.body, text=t("shift.open"), style="Big.TButton", command=self.open).pack(anchor=rtl.anchor, pady=8)
        else:
            ttk.Label(self.body, text=t("shift.opening_float") + ": " + self.app.p.fmt.money(self.shift.opening_float)).pack(anchor=rtl.anchor)
            self.amount = FormRow.entry(self.body, rtl, t("shift.counted"))
            self.amount.focus_set()
            ttk.Button(self.body, text=t("shift.close"), style="Big.TButton", command=self.close).pack(anchor=rtl.anchor, pady=8)

    def open(self) -> None:
        if self.app.report(self.c.open(self.amount.var.get())):                  # type: ignore[attr-defined]
            self.app.refresh_shift_label()
            self.refresh()

    def close(self, force: bool = False, cred=None) -> None:
        counted = self.amount.var.get()                                          # type: ignore[attr-defined]
        user, secret = cred or ("", "")
        out = self.c.close(self.shift.shift_id, counted, force, user, secret)
        if not out.ok and out.error_type == "ParkedSalesExist":
            if messagebox.askyesno(self.t("app.confirm"), self.t("shift.parked_prompt"), parent=self):
                return self.close(True, cred)
            self.app.notify(out.error, error=True)
            return
        if not out.ok and out.error_type in ("ApprovalRequired", "ApprovalRejected") and cred is None:
            cred = self.app.prompt_approver(self)
            if cred:
                return self.close(force, cred)
        if not self.app.report(out, modal=True):
            return
        self.app.refresh_shift_label()
        for w in self.body.winfo_children():
            w.destroy()
        ttk.Label(self.body, text=self.t("shift.z_report"), font=("Segoe UI", 14, "bold")).pack(anchor=self.rtl.anchor, pady=8)
        table = DataTable(self.body, self.rtl, [("k", "", 260), ("v", "", 160)], height=18)
        table.tree.configure(show="tree")
        table.set_rows(out.value)
        table.pack(anchor=self.rtl.anchor)
        ttk.Button(self.body, text=self.t("shift.new"), command=self.refresh).pack(anchor=self.rtl.anchor, pady=10)
