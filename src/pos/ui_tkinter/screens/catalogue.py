"""Catalogue screen: products, categories, customers (UC-10)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..widgets import DataTable, FormRow


class CatalogueScreen(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.c = app, app.c.catalogue
        self.rtl, self.t = app.rtl, app.t
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True)
        for builder, key in ((self._products_tab, "cat.products"), (self._categories_tab, "cat.categories"),
                             (self._customers_tab, "cat.customers")):
            tab = ttk.Frame(nb, padding=8)
            nb.add(tab, text=self.t(key))
            builder(tab)

    # ---- products ------------------------------------------------------------------
    def _products_tab(self, tab) -> None:
        rtl, t = self.rtl, self.t
        left = ttk.Frame(tab)
        left.pack(side=rtl.start, fill=tk.BOTH, expand=True)
        self.q = tk.StringVar()
        ttk.Entry(left, textvariable=self.q, justify=rtl.justify).pack(fill=tk.X, pady=(0, 6))
        self.q.trace_add("write", lambda *_: self.load_products())
        self.ptable = DataTable(left, rtl, [("sku", "SKU", 90), ("bc", t("col.barcode"), 120), ("name", t("col.item"), 200),
                                            ("price", t("col.price"), 80), ("stock", t("col.stock"), 70),
                                            ("act", t("col.active"), 50)], height=18, on_select=self.pick_product)
        self.ptable.pack(fill=tk.BOTH, expand=True)
        form = ttk.Frame(tab, padding=(12, 0))
        form.pack(side=rtl.start, fill=tk.Y)
        self.pid = None
        self.f = {k: FormRow.entry(form, rtl, t(lbl), width=24) for k, lbl in (
            ("sku", "col.sku"), ("barcode", "col.barcode"), ("name_en", "cat.name_en"), ("name_ar", "cat.name_ar"),
            ("price", "col.price"), ("cost", "cat.cost"), ("reorder", "cat.reorder"))}
        self.unit = tk.StringVar(value="PIECE")
        row = ttk.Frame(form)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text=t("cat.unit"), width=18, anchor=rtl.anchor).pack(side=rtl.start)
        ttk.Combobox(row, textvariable=self.unit, values=("PIECE", "KG"), width=10, state="readonly").pack(side=rtl.start)
        self.cat = tk.StringVar()
        self.cat_ids: dict[str, str] = {}
        row = ttk.Frame(form)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text=t("cat.category"), width=18, anchor=rtl.anchor).pack(side=rtl.start)
        self.cat_box = ttk.Combobox(row, textvariable=self.cat, width=22, state="readonly")
        self.cat_box.pack(side=rtl.start)
        self.active = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text=t("col.active"), variable=self.active).pack(anchor=rtl.anchor)
        bar = ttk.Frame(form)
        bar.pack(fill=tk.X, pady=8)
        ttk.Button(bar, text=t("save"), command=self.save_product).pack(side=rtl.start, padx=3)
        ttk.Button(bar, text=t("cat.new"), command=self.clear_form).pack(side=rtl.start)
        self.load_categories()
        self.load_products()

    def load_categories(self) -> None:
        out = self.c.categories()
        self.cat_ids = {}
        if out.ok:
            for cat in out.value:
                self.cat_ids[self.app.p.category_label(cat)] = cat.id
        self.cat_box.configure(values=list(self.cat_ids))

    def load_products(self) -> None:
        out = self.c.products(self.q.get())
        self.products = {}
        if self.app.report(out):
            self.products = {p.id: p for p in out.value}
            self.ptable.set_rows([self.app.p.product_row(p) for p in out.value], [p.id for p in out.value])

    def pick_product(self) -> None:
        iid = self.ptable.selected()
        p = self.products.get(iid) if iid else None
        if not p:
            return
        self.pid = p.id
        fmt = self.app.p.fmt
        for key, val in (("sku", p.sku), ("barcode", p.barcode or ""), ("name_en", p.name_en), ("name_ar", p.name_ar),
                         ("price", fmt.money(p.price, False)), ("cost", fmt.money(p.cost, False)),
                         ("reorder", str(p.reorder_level))):
            self.f[key].var.set(val.replace(",", ""))                          # type: ignore[attr-defined]
        self.unit.set(p.unit)
        self.active.set(p.is_active)
        self.cat.set(next((l for l, i in self.cat_ids.items() if i == p.category_id), ""))

    def clear_form(self) -> None:
        self.pid = None
        for e in self.f.values():
            e.var.set("")                                                       # type: ignore[attr-defined]
        self.active.set(True)

    def save_product(self) -> None:
        form = {k: e.var.get() for k, e in self.f.items()}                      # type: ignore[attr-defined]
        form.update(unit=self.unit.get(), category_id=self.cat_ids.get(self.cat.get(), ""), active=self.active.get())
        out = self.c.save_product(self.pid, form)
        if self.app.report(out, modal=not out.ok):
            self.pid = out.value.id
            self.load_products()
            self.ptable.select(self.pid)

    # ---- categories ------------------------------------------------------------------
    def _categories_tab(self, tab) -> None:
        rtl, t = self.rtl, self.t
        self.ctable = DataTable(tab, rtl, [("en", t("cat.name_en"), 160), ("ar", t("cat.name_ar"), 160),
                                           ("tax", t("cat.tax_percent"), 80), ("inc", t("cat.inclusive"), 80)],
                                height=12, on_select=self.pick_category)
        self.ctable.pack(side=rtl.start, fill=tk.BOTH, expand=True)
        form = ttk.Frame(tab, padding=(12, 0))
        form.pack(side=rtl.start, fill=tk.Y)
        self.cid = None
        self.cf = {k: FormRow.entry(form, rtl, t(lbl), width=22) for k, lbl in (
            ("en", "cat.name_en"), ("ar", "cat.name_ar"), ("tax", "cat.tax_percent"))}
        self.cf["tax"].var.set("0")                                              # type: ignore[attr-defined]
        self.inclusive = tk.BooleanVar()
        ttk.Checkbutton(form, text=t("cat.inclusive"), variable=self.inclusive).pack(anchor=rtl.anchor)
        ttk.Button(form, text=t("save"), command=self.save_category).pack(pady=8, anchor=rtl.anchor)
        ttk.Button(form, text=t("cat.new"), command=lambda: self._reset_cat()).pack(anchor=rtl.anchor)
        self.load_category_table()

    def _reset_cat(self) -> None:
        self.cid = None
        for k, e in self.cf.items():
            e.var.set("0" if k == "tax" else "")                                  # type: ignore[attr-defined]

    def load_category_table(self) -> None:
        out = self.c.categories()
        self.cats = {c.id: c for c in out.value} if out.ok else {}
        self.ctable.set_rows([(c.name_en, c.name_ar, f"{c.tax_bp / 100:g}", self.t("yes") if c.tax_inclusive else self.t("no"))
                              for c in self.cats.values()], list(self.cats))

    def pick_category(self) -> None:
        iid = self.ctable.selected()
        c = self.cats.get(iid) if iid else None
        if c:
            self.cid = c.id
            self.cf["en"].var.set(c.name_en)                                      # type: ignore[attr-defined]
            self.cf["ar"].var.set(c.name_ar)                                      # type: ignore[attr-defined]
            self.cf["tax"].var.set(f"{c.tax_bp / 100:g}")                         # type: ignore[attr-defined]
            self.inclusive.set(c.tax_inclusive)

    def save_category(self) -> None:
        out = self.c.save_category(self.cid, self.cf["ar"].var.get(), self.cf["en"].var.get(),      # type: ignore[attr-defined]
                                   self.cf["tax"].var.get(), self.inclusive.get())                   # type: ignore[attr-defined]
        if self.app.report(out, modal=not out.ok):
            self.cid = out.value.id
            self.load_category_table()
            self.load_categories()

    # ---- customers -------------------------------------------------------------------
    def _customers_tab(self, tab) -> None:
        rtl, t = self.rtl, self.t
        left = ttk.Frame(tab)
        left.pack(side=rtl.start, fill=tk.BOTH, expand=True)
        self.cq = tk.StringVar()
        ttk.Entry(left, textvariable=self.cq, justify=rtl.justify).pack(fill=tk.X, pady=(0, 6))
        self.cq.trace_add("write", lambda *_: self.load_customers())
        self.cutable = DataTable(left, rtl, [("name", t("col.name"), 200), ("phone", t("col.phone"), 120),
                                             ("loy", t("col.loyalty"), 100)], height=14, on_select=self.pick_customer)
        self.cutable.pack(fill=tk.BOTH, expand=True)
        form = ttk.Frame(tab, padding=(12, 0))
        form.pack(side=rtl.start, fill=tk.Y)
        self.cuid = None
        self.cuf = {k: FormRow.entry(form, rtl, t(lbl), width=22) for k, lbl in (
            ("name", "col.name"), ("phone", "col.phone"), ("loy", "col.loyalty"))}
        ttk.Button(form, text=t("save"), command=self.save_customer).pack(pady=8, anchor=rtl.anchor)
        ttk.Button(form, text=t("cat.new"), command=self._reset_customer).pack(anchor=rtl.anchor)
        self.load_customers()

    def _reset_customer(self) -> None:
        self.cuid = None
        for e in self.cuf.values():
            e.var.set("")                                                          # type: ignore[attr-defined]

    def load_customers(self) -> None:
        out = self.c.customers(self.cq.get())
        self.customers = {c.id: c for c in out.value} if out.ok else {}
        self.cutable.set_rows([(c.name, c.phone or "", c.loyalty_id or "") for c in self.customers.values()], list(self.customers))

    def pick_customer(self) -> None:
        iid = self.cutable.selected()
        c = self.customers.get(iid) if iid else None
        if c:
            self.cuid = c.id
            for k, v in (("name", c.name), ("phone", c.phone or ""), ("loy", c.loyalty_id or "")):
                self.cuf[k].var.set(v)                                              # type: ignore[attr-defined]

    def save_customer(self) -> None:
        out = self.c.save_customer(self.cuid, self.cuf["name"].var.get(), self.cuf["phone"].var.get(),   # type: ignore[attr-defined]
                                   self.cuf["loy"].var.get())                                             # type: ignore[attr-defined]
        if self.app.report(out, modal=not out.ok):
            self.cuid = out.value.id
            self.load_customers()
