"""Stock screen: on-hand levels, receive / adjust / waste, low-stock alerts (UC-11)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..widgets import DataTable, FormRow, ask_values


class StockScreen(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.c = app, app.c.catalogue
        self.rtl, self.t = app.rtl, app.t
        rtl, t = self.rtl, self.t
        top = ttk.Frame(self)
        top.pack(fill=tk.X)
        self.q = tk.StringVar()
        ttk.Entry(top, textvariable=self.q, width=30, justify=rtl.justify).pack(side=rtl.start)
        self.q.trace_add("write", lambda *_: self.load())
        self.low_only = tk.BooleanVar()
        ttk.Checkbutton(top, text=t("stock.low_only"), variable=self.low_only, command=self.load).pack(side=rtl.start, padx=10)
        self.table = DataTable(self, rtl, [("sku", "SKU", 100), ("name", t("col.item"), 240), ("stock", t("col.stock"), 90),
                                           ("re", t("cat.reorder"), 90), ("low", t("stock.low"), 70)], height=16)
        self.table.pack(fill=tk.BOTH, expand=True, pady=8)
        bar = ttk.Frame(self)
        bar.pack(fill=tk.X)
        for kind, key in (("RECEIPT", "stock.receive"), ("ADJUSTMENT", "stock.adjust"), ("WASTE", "stock.waste")):
            ttk.Button(bar, text=t(key), command=lambda k=kind: self.adjust(k)).pack(side=rtl.start, padx=4)
        self.load()

    def load(self) -> None:
        out = self.c.low_stock() if self.low_only.get() else self.c.products(self.q.get())
        if not self.app.report(out):
            return
        fmt = self.app.p.fmt
        products = [p for p in out.value if p.is_active]
        self.products = {p.id: p for p in products}
        self.table.set_rows([(p.sku, self.app.p.name(p.name_en, p.name_ar), fmt.qty(p.on_hand or 0),
                              fmt.qty(p.reorder_level), "⚠" if (p.on_hand or 0) <= p.reorder_level else "")
                             for p in products], [p.id for p in products])

    def adjust(self, kind: str) -> None:
        iid = self.table.selected()
        if not iid:
            self.app.notify(self.t("stock.select"), error=True)
            return
        hint = "stock.signed_hint" if kind == "ADJUSTMENT" else "stock.positive_hint"
        v = ask_values(self, self.rtl, self.t("stock." + {"RECEIPT": "receive", "ADJUSTMENT": "adjust", "WASTE": "waste"}[kind]),
                       [("q", self.t("col.qty") + " (" + self.t(hint) + ")", False), ("r", self.t("stock.reason"), False)],
                       self.t("ok"), self.t("cancel"))
        if v:
            out = self.c.adjust_stock(iid, kind, v["q"], v["r"])
            if self.app.report(out, modal=not out.ok):
                self.load()
                self.table.select(iid)
