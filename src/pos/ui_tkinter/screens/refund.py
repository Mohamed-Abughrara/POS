"""Refund screen (UC-09)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..widgets import DataTable, FormRow, ask_values


class RefundScreen(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.c = app, app.c.refund
        self.rtl, self.t = app.rtl, app.t
        self.number = ""
        self.qty_vars: dict[int, str] = {}
        rtl, t = self.rtl, self.t
        top = ttk.Frame(self)
        top.pack(fill=tk.X)
        ttk.Label(top, text=t("refund.receipt_no")).pack(side=rtl.start)
        self.no_var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.no_var, width=14, justify=rtl.justify)
        entry.pack(side=rtl.start, padx=6)
        entry.bind("<Return>", lambda _e: self.lookup())
        ttk.Button(top, text=t("refund.find"), command=self.lookup).pack(side=rtl.start)
        entry.focus_set()
        self.table = DataTable(self, rtl, [("n", "#", 40), ("name", t("col.item"), 260), ("sold", t("refund.sold"), 80),
                                           ("done", t("refund.refunded"), 80), ("rem", t("refund.remaining"), 80)],
                               height=10, on_double=self.set_qty)
        self.table.pack(fill=tk.X, pady=10)
        ttk.Label(self, text=t("refund.hint")).pack(anchor=rtl.anchor)
        self.summary = ttk.Label(self, text="")
        self.summary.pack(anchor=rtl.anchor, pady=4)
        self.method = tk.StringVar(value="CASH")
        row = ttk.Frame(self)
        row.pack(fill=tk.X)
        ttk.Radiobutton(row, text=t("pay.cash"), variable=self.method, value="CASH").pack(side=rtl.start, padx=6)
        ttk.Radiobutton(row, text=t("pay.card"), variable=self.method, value="CARD").pack(side=rtl.start)
        self.reason = FormRow.entry(self, rtl, t("refund.reason"), width=50)
        ttk.Button(self, text=t("refund.process"), style="Big.TButton", command=self.process).pack(anchor=rtl.anchor, pady=10)

    def lookup(self) -> None:
        out = self.c.lookup(self.no_var.get())
        if not self.app.report(out):
            return
        _view, rows = out.value
        self.number = self.no_var.get()
        self.qty_vars = {}
        self.table.set_rows(rows, [str(r[0]) for r in rows])
        self._summary()

    def set_qty(self) -> None:
        iid = self.table.selected()
        if not iid:
            return
        v = ask_values(self, self.rtl, self.t("refund.qty"), [("q", self.t("col.qty"), False)], self.t("ok"),
                       self.t("cancel"), {"q": self.qty_vars.get(int(iid), "")})
        if v is not None:
            self.qty_vars[int(iid)] = v["q"]
            self._summary()

    def _summary(self) -> None:
        picked = {n: q for n, q in self.qty_vars.items() if q.strip()}
        self.summary.configure(text=self.t("refund.selected", n=self.app.p.fmt.number(len(picked))))

    def process(self) -> None:
        if not self.qty_vars:
            self.app.notify(self.t("refund.nothing"), error=True)
            return
        args = (self.number, self.qty_vars, self.method.get(), self.reason.var.get())      # type: ignore[attr-defined]
        out = self.c.refund(*args)
        if not out.ok and out.error_type in ("ApprovalRequired", "ApprovalRejected"):
            cred = self.app.prompt_approver(self)
            if cred:
                out = self.c.refund(*args, cred[0], cred[1])
        if self.app.report(out, modal=True):
            self.qty_vars = {}
            self.lookup()
