"""Reports screen (UC-13)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..widgets import DataTable

KINDS = ("DAILY", "BY_PRODUCT", "BY_CASHIER", "BY_PAYMENT", "TAX")


class ReportsScreen(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.c = app, app.c.report
        self.rtl, self.t = app.rtl, app.t
        rtl, t = self.rtl, self.t
        top = ttk.Frame(self)
        top.pack(fill=tk.X)
        self.kind = tk.StringVar(value="DAILY")
        labels = {t("report." + k): k for k in KINDS}
        self.label_to_kind = labels
        self.box = ttk.Combobox(top, values=list(labels), state="readonly", width=24)
        self.box.set(t("report.DAILY"))
        self.box.pack(side=rtl.start)
        start, end = self.c.default_range()
        self.d_from, self.d_to = tk.StringVar(value=start), tk.StringVar(value=end)
        ttk.Label(top, text=t("report.from")).pack(side=rtl.start, padx=(12, 2))
        ttk.Entry(top, textvariable=self.d_from, width=12, justify=rtl.justify).pack(side=rtl.start)
        ttk.Label(top, text=t("report.to")).pack(side=rtl.start, padx=(12, 2))
        ttk.Entry(top, textvariable=self.d_to, width=12, justify=rtl.justify).pack(side=rtl.start)
        ttk.Button(top, text=t("report.run"), command=self.run).pack(side=rtl.start, padx=10)
        ttk.Button(top, text=t("report.export"), command=self.export).pack(side=rtl.start)
        self.holder = ttk.Frame(self)
        self.holder.pack(fill=tk.BOTH, expand=True, pady=10)
        self.run()

    def _kind(self) -> str:
        return self.label_to_kind.get(self.box.get(), "DAILY")

    def run(self) -> None:
        out = self.c.run(self._kind(), self.d_from.get(), self.d_to.get())
        for w in self.holder.winfo_children():
            w.destroy()
        if not self.app.report(out):
            return
        vm = out.value
        table = DataTable(self.holder, self.rtl, [(f"c{i}", name, 120) for i, name in enumerate(vm.columns)], height=18)
        rows = vm.rows + ([vm.totals] if vm.totals else [])
        table.set_rows(rows)
        table.pack(fill=tk.BOTH, expand=True)

    def export(self) -> None:
        self.app.report(self.c.export(self._kind(), self.d_from.get(), self.d_to.get()), modal=True)
