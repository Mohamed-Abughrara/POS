"""Checkout screen (UC-03..UC-08). The view only renders view-models and forwards events."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

from ...adapters.presenters import CartVM
from ..widgets import DataTable, Dialog, FormRow, ask_values


class CheckoutScreen(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.c = app, app.c.checkout
        self.rtl, self.t = app.rtl, app.t
        self.cart: Optional[CartVM] = None
        self._build()
        self._render(None)
        self.scan_entry.focus_set()

    # ---- layout -----------------------------------------------------------------
    def _build(self) -> None:
        rtl, t = self.rtl, self.t
        top = ttk.Frame(self)
        top.pack(fill=tk.X)
        ttk.Label(top, text=t("checkout.scan")).pack(side=rtl.start)
        self.scan_var = tk.StringVar()
        self.scan_entry = ttk.Entry(top, textvariable=self.scan_var, font=("Segoe UI", 14), width=30, justify=rtl.justify)
        self.scan_entry.pack(side=rtl.start, padx=8)
        self.scan_entry.bind("<Return>", self._on_scan)
        ttk.Button(top, text=t("checkout.search") + " (F3)", command=self.search_products).pack(side=rtl.start)
        self.customer_label = ttk.Label(top, text="")
        self.customer_label.pack(side=rtl.end)

        main = ttk.Frame(self)
        main.pack(fill=tk.BOTH, expand=True, pady=8)
        side = ttk.Frame(main, padding=(10, 0))
        side.pack(side=rtl.end, fill=tk.Y)
        cols = [("n", "#", 40), ("name", t("col.item"), 260), ("qty", t("col.qty"), 70),
                ("price", t("col.price"), 90), ("disc", t("col.discount"), 80), ("tax", t("col.tax"), 70),
                ("total", t("col.total"), 100)]
        self.table = DataTable(main, rtl, cols, height=16)
        self.table.pack(side=rtl.start, fill=tk.BOTH, expand=True)

        self.v_sub, self.v_disc, self.v_tax, self.v_total = (tk.StringVar() for _ in range(4))
        for label, var in ((t("checkout.subtotal"), self.v_sub), (t("checkout.discount"), self.v_disc),
                           (t("checkout.tax"), self.v_tax)):
            row = ttk.Frame(side)
            row.pack(fill=tk.X)
            ttk.Label(row, text=label, anchor=rtl.anchor).pack(side=rtl.start)
            ttk.Label(row, textvariable=var).pack(side=rtl.end)
        ttk.Label(side, text=t("checkout.total"), anchor=rtl.anchor).pack(fill=tk.X, pady=(12, 0))
        ttk.Label(side, textvariable=self.v_total, style="Total.TLabel").pack(fill=tk.X)

        buttons = [
            ("checkout.qty", "F4", self.change_qty), ("checkout.line_discount", "F5", self.line_discount),
            ("checkout.cart_discount", "F6", self.cart_discount), ("checkout.customer", "F7", self.pick_customer),
            ("checkout.park", "F8", self.park), ("checkout.recall", "F9", self.recall),
            ("checkout.remove", "F10", self.remove_line), ("checkout.void", "F11", self.void),
            ("checkout.reprint", "", self.reprint)]
        grid = ttk.Frame(side)
        grid.pack(fill=tk.X, pady=10)
        for label_key, fkey, fn in buttons:
            ttk.Button(grid, text=t(label_key) + (f" ({fkey})" if fkey else ""), command=fn).pack(fill=tk.X, pady=2)
            if fkey:
                app_root = self.app.root
                app_root.bind(f"<{fkey}>", lambda _e, f=fn: f())
        self.pay_btn = ttk.Button(side, text=t("checkout.pay") + " (F12)", style="Pay.TButton", command=self.pay)
        self.pay_btn.pack(fill=tk.X, pady=(10, 0))
        root = self.app.root
        root.bind("<F2>", lambda _e: self.scan_entry.focus_set())
        root.bind("<F3>", lambda _e: self.search_products())
        root.bind("<F12>", lambda _e: self.pay())
        self.table.tree.bind("<Delete>", lambda _e: self.remove_line())
        self.bind("<Destroy>", self._unbind_keys)

    def _unbind_keys(self, event) -> None:
        if event.widget is self:
            for k in ("F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"):
                try:
                    self.app.root.unbind(f"<{k}>")
                except tk.TclError:
                    pass

    # ---- rendering -----------------------------------------------------------------
    def _render(self, cart: Optional[CartVM]) -> None:
        self.cart = cart
        fmt = self.app.p.fmt
        rows = [(l.line_no, l.name, l.qty, l.unit_price, l.discount, l.tax, l.total) for l in (cart.lines if cart else [])]
        self.table.set_rows(rows, [str(l.line_no) for l in cart.lines] if cart else None)
        self.v_sub.set(cart.subtotal if cart else fmt.money(0))
        self.v_disc.set(cart.discount if cart else fmt.money(0))
        self.v_tax.set(cart.tax if cart else fmt.money(0))
        self.v_total.set(cart.total if cart else fmt.money(0))
        self.pay_btn.state(["!disabled"] if cart and cart.can_pay else ["disabled"])
        cust = self.c.customer
        self.customer_label.configure(text=(self.t("checkout.customer") + ": " + cust.name) if cust else "")
        children = self.table.tree.get_children()
        if children:
            self.table.select(children[-1])
        self.scan_entry.focus_set()

    def _apply(self, outcome) -> bool:
        if not self.app.report(outcome):
            self.scan_entry.focus_set()
            return False
        self._render(outcome.value)
        return True

    def _line_no(self) -> Optional[int]:
        iid = self.table.selected()
        if iid is None:
            self.app.notify(self.t("checkout.select_line"), error=True)
            return None
        return int(iid)

    # ---- actions --------------------------------------------------------------------
    def _on_scan(self, _e=None) -> None:
        text = self.scan_var.get().strip()
        self.scan_var.set("")
        if not text:
            return
        qty = "1"
        if "*" in text:                      # "3*622000..." = quantity prefix
            qty, text = (x.strip() for x in text.split("*", 1))
        self._apply(self.c.scan(text, qty))

    def search_products(self) -> None:
        dlg = Dialog(self, self.t("checkout.search"), self.rtl)
        q = tk.StringVar()
        entry = ttk.Entry(dlg.body, textvariable=q, width=40, justify=self.rtl.justify)
        entry.pack(fill=tk.X)
        table = DataTable(dlg.body, self.rtl, [("sku", "SKU", 90), ("name", self.t("col.item"), 240),
                                               ("price", self.t("col.price"), 90)], height=10,
                          on_double=lambda: choose())
        table.pack(pady=8)
        found: dict[str, str] = {}

        def refresh(*_):
            out = self.c.find_products(q.get())
            found.clear()
            rows = []
            if out.ok:
                for p in out.value:
                    found[p.sku] = p.sku
                    rows.append((p.sku, self.app.p.name(p.name_en, p.name_ar), self.app.p.fmt.money(p.price, False)))
            table.set_rows(rows, [r[0] for r in rows])

        def choose():
            sku = table.selected()
            if sku:
                dlg.close(sku)

        q.trace_add("write", refresh)
        refresh()
        entry.focus_set()
        dlg.buttons(self.t("checkout.add"), self.t("cancel"), choose)
        sku = dlg.show()
        if sku:
            self._apply(self.c.scan(sku))
        self.scan_entry.focus_set()

    def change_qty(self) -> None:
        n = self._line_no()
        if n is None:
            return
        v = ask_values(self, self.rtl, self.t("checkout.qty"), [("q", self.t("col.qty"), False)],
                       self.t("ok"), self.t("cancel"))
        if v:
            self._apply(self.c.set_quantity(n, v["q"]))

    def remove_line(self) -> None:
        n = self._line_no()
        if n is not None:
            self._apply(self.c.remove_line(n))

    def _discount_dialog(self, target: str, line_no: Optional[int]) -> None:
        dlg = Dialog(self, self.t("checkout.line_discount" if target == "LINE" else "checkout.cart_discount"), self.rtl)
        kind = tk.StringVar(value="PERCENT")
        row = ttk.Frame(dlg.body)
        row.pack(fill=tk.X)
        ttk.Radiobutton(row, text="%", variable=kind, value="PERCENT").pack(side=self.rtl.start, padx=6)
        ttk.Radiobutton(row, text=self.t("checkout.fixed"), variable=kind, value="FIXED").pack(side=self.rtl.start)
        value = FormRow.entry(dlg.body, self.rtl, self.t("checkout.value"))
        dlg.after(50, value.focus_set)
        dlg.buttons(self.t("ok"), self.t("cancel"), lambda: dlg.close((kind.get(), value.var.get())))   # type: ignore[attr-defined]
        res = dlg.show()
        if not res:
            return
        out = self.c.discount(target, res[0], res[1], line_no)
        if not out.ok and out.error_type in ("DiscountLimitExceeded", "ApprovalRequired"):
            cred = self.app.prompt_approver(self)
            if cred:
                out = self.c.discount(target, res[0], res[1], line_no, cred[0], cred[1])
        self._apply(out)

    def line_discount(self) -> None:
        n = self._line_no()
        if n is not None:
            self._discount_dialog("LINE", n)

    def cart_discount(self) -> None:
        if self.cart and not self.cart.is_empty:
            self._discount_dialog("CART", None)

    def pick_customer(self) -> None:
        dlg = Dialog(self, self.t("checkout.customer"), self.rtl)
        q = tk.StringVar()
        ttk.Entry(dlg.body, textvariable=q, width=40, justify=self.rtl.justify).pack(fill=tk.X)
        table = DataTable(dlg.body, self.rtl, [("name", self.t("col.name"), 180), ("phone", self.t("col.phone"), 120),
                                               ("loy", self.t("col.loyalty"), 100)], height=8,
                          on_double=lambda: choose())
        table.pack(pady=8)
        found = {}

        def refresh(*_):
            out = self.c.find_customers(q.get())
            found.clear()
            if out.ok:
                for c in out.value:
                    found[c.id] = c
            table.set_rows([(c.name, c.phone or "", c.loyalty_id or "") for c in found.values()], list(found))

        def choose():
            iid = table.selected()
            if iid:
                dlg.close(found[iid])

        def new_customer():
            v = ask_values(dlg, self.rtl, self.t("customer.new"),
                           [("name", self.t("col.name"), False), ("phone", self.t("col.phone"), False),
                            ("loy", self.t("col.loyalty"), False)], self.t("ok"), self.t("cancel"))
            if v:
                out = self.c.add_customer(v["name"], v["phone"], v["loy"])
                if self.app.report(out, modal=True):
                    dlg.close(out.value)

        q.trace_add("write", refresh)
        refresh()
        bar = ttk.Frame(dlg.body)
        bar.pack(fill=tk.X)
        ttk.Button(bar, text=self.t("customer.new"), command=new_customer).pack(side=self.rtl.start)
        ttk.Button(bar, text=self.t("customer.clear"), command=lambda: dlg.close("CLEAR")).pack(side=self.rtl.start, padx=6)
        dlg.buttons(self.t("ok"), self.t("cancel"), choose)
        res = dlg.show()
        if res == "CLEAR":
            self.c.attach_customer(None)
        elif res:
            self.c.attach_customer(res)
        self._render(self.cart)

    def park(self) -> None:
        if self.cart and not self.cart.is_empty and self.app.report(self.c.park()):
            self._render(None)

    def recall(self) -> None:
        out = self.c.parked()
        if not self.app.report(out):
            return
        if not out.value:
            self.app.notify(self.t("checkout.no_parked"), error=True)
            return
        dlg = Dialog(self, self.t("checkout.recall"), self.rtl)
        table = DataTable(dlg.body, self.rtl, [("time", self.t("col.time"), 150), ("lines", self.t("col.lines"), 60),
                                               ("total", self.t("col.total"), 100)], height=8, on_double=lambda: choose())
        table.set_rows([r[1:] for r in out.value], [r[0] for r in out.value])
        table.pack()

        def choose():
            iid = table.selected()
            if iid:
                dlg.close(iid)

        dlg.buttons(self.t("ok"), self.t("cancel"), choose)
        sale_id = dlg.show()
        if sale_id:
            self._apply(self.c.recall(sale_id))

    def void(self) -> None:
        if self.cart and not self.cart.is_empty and self.app.report(self.c.void_cart()):
            self._render(None)

    def reprint(self) -> None:
        v = ask_values(self, self.rtl, self.t("checkout.reprint"), [("n", self.t("refund.receipt_no"), False)],
                       self.t("ok"), self.t("cancel"))
        if v:
            self.app.report(self.c.reprint(v["n"]), modal=False)

    def pay(self) -> None:
        if not self.cart or not self.cart.can_pay:
            return
        cart = self.cart
        dlg = Dialog(self, self.t("pay.title"), self.rtl)
        ttk.Label(dlg.body, text=self.t("checkout.total") + ": " + cart.total, style="Total.TLabel").pack(pady=(0, 10))
        method = tk.StringVar(value="CASH")
        row = ttk.Frame(dlg.body)
        row.pack(fill=tk.X)
        for key, text in (("CASH", "pay.cash"), ("CARD", "pay.card"), ("SPLIT", "pay.split")):
            ttk.Radiobutton(row, text=self.t(text), variable=method, value=key).pack(side=self.rtl.start, padx=6)
        tendered = FormRow.entry(dlg.body, self.rtl, self.t("pay.tendered"))
        split_cash = FormRow.entry(dlg.body, self.rtl, self.t("pay.split_cash"))
        ref = FormRow.entry(dlg.body, self.rtl, self.t("pay.card_ref"))
        change = ttk.Label(dlg.body, text="", font=("Segoe UI", 13, "bold"))
        change.pack(pady=6)
        error = ttk.Label(dlg.body, text="", style="Err.TLabel", wraplength=340)
        error.pack()

        def update_change(*_):
            if method.get() == "CASH":
                change.configure(text=self.t("pay.change") + ": " + self.c.change_preview(tendered.var.get(), cart.total_raw))  # type: ignore[attr-defined]
            else:
                change.configure(text="")

        tendered.var.trace_add("write", update_change)      # type: ignore[attr-defined]
        method.trace_add("write", update_change)
        dlg.after(50, tendered.focus_set)

        def confirm():
            m = method.get()
            if m == "CASH":
                out = self.c.pay_cash(tendered.var.get(), cart.total_raw)                            # type: ignore[attr-defined]
            elif m == "CARD":
                out = self.c.pay_card(ref.var.get(), cart.total_raw)                                 # type: ignore[attr-defined]
            else:
                out = self.c.pay_split(split_cash.var.get(), ref.var.get(), cart.total_raw)          # type: ignore[attr-defined]
            if out.ok:
                dlg.close(out)
            else:
                error.configure(text=out.error)

        dlg.buttons(self.t("pay.confirm"), self.t("cancel"), confirm)
        out = dlg.show()
        if out:
            self.app.report(out)
            self._render(None)
        self.scan_entry.focus_set()
