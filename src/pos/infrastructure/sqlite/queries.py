"""Read-model queries for reports and shift totals (plain SQL over stored totals)."""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Optional

from ...application.dto import ShiftTotals
from ...application.errors import InvalidInput

_DONE = "s.status='COMPLETED' AND substr(s.completed_at,1,10) BETWEEN ? AND ?"


class SqliteReportQueries:
    def __init__(self, conn: sqlite3.Connection):
        self.c = conn

    def shift_totals(self, shift_id: str) -> ShiftTotals:
        r = self.c.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(total),0) gross, COALESCE(SUM(discount_total),0) disc,"
            " COALESCE(SUM(tax_total),0) tax FROM sales WHERE shift_id=? AND status='COMPLETED'",
            (shift_id,)).fetchone()
        by_method = {m["method"]: m["amt"] for m in self.c.execute(
            "SELECT p.method, SUM(p.amount) amt FROM payments p JOIN sales s ON s.id=p.sale_id "
            "WHERE s.shift_id=? AND s.status='COMPLETED' GROUP BY p.method", (shift_id,))}
        refunds = {m["method"]: m["amt"] for m in self.c.execute(
            "SELECT method, SUM(amount) amt FROM refunds WHERE shift_id=? GROUP BY method", (shift_id,))}
        return ShiftTotals(r["n"], r["gross"], r["disc"], r["tax"], sum(refunds.values()),
                           by_method.get("CASH", 0), refunds.get("CASH", 0), by_method)

    def run(self, kind: str, date_from: date, date_to: date, cashier_id: Optional[str] = None):
        args: list = [date_from.isoformat(), date_to.isoformat()]
        cash = ""
        if cashier_id:
            cash, args = " AND s.cashier_id=?", args + [cashier_id]
        if kind == "DAILY":
            cols = ["date", "count", "gross", "discounts", "tax", "refunds", "net"]
            sales = {r["d"]: r for r in self.c.execute(
                f"SELECT substr(s.completed_at,1,10) d, COUNT(*) n, SUM(s.total) t, SUM(s.discount_total) dd,"
                f" SUM(s.tax_total) tx FROM sales s WHERE {_DONE}{cash} GROUP BY d", args)}
            refunds = {r["d"]: r["a"] for r in self.c.execute(
                "SELECT substr(created_at,1,10) d, SUM(amount) a FROM refunds "
                "WHERE substr(created_at,1,10) BETWEEN ? AND ? GROUP BY d", args[:2])} if not cashier_id else {}
            rows = []
            for d in sorted(set(sales) | set(refunds)):
                s = sales.get(d)
                n, t, dd, tx = (s["n"], s["t"], s["dd"], s["tx"]) if s else (0, 0, 0, 0)
                rf = refunds.get(d, 0)
                rows.append([d, n, t, dd, tx, rf, t - rf])
            return cols, rows, self._totals(rows, 1)
        if kind == "BY_PRODUCT":
            cols = ["product", "qty", "gross", "tax", "total"]
            rows = [[r["name"], r["q"] / 1000, r["g"], r["tx"], r["t"]] for r in self.c.execute(
                f"SELECT l.name, SUM(l.qty_milli) q, SUM(ROUND(l.unit_price * l.qty_milli / 1000.0)) g,"
                f" SUM(l.line_tax) tx, SUM(l.line_total) t FROM sale_lines l JOIN sales s ON s.id=l.sale_id"
                f" WHERE {_DONE}{cash} GROUP BY l.product_id ORDER BY t DESC", args)]
            return cols, rows, self._totals(rows, 1)
        if kind == "BY_CASHIER":
            cols = ["cashier", "count", "total", "discounts"]
            rows = [[r["display_name"], r["n"], r["t"], r["d"]] for r in self.c.execute(
                f"SELECT u.display_name, COUNT(*) n, SUM(s.total) t, SUM(s.discount_total) d FROM sales s"
                f" JOIN users u ON u.id=s.cashier_id WHERE {_DONE}{cash} GROUP BY s.cashier_id ORDER BY t DESC", args)]
            return cols, rows, self._totals(rows, 1)
        if kind == "BY_PAYMENT":
            cols = ["method", "count", "amount"]
            rows = [[r["method"], r["n"], r["a"]] for r in self.c.execute(
                f"SELECT p.method, COUNT(*) n, SUM(p.amount) a FROM payments p JOIN sales s ON s.id=p.sale_id"
                f" WHERE {_DONE}{cash} GROUP BY p.method", args)]
            return cols, rows, self._totals(rows, 1)
        if kind == "TAX":
            cols = ["tax_rate", "net", "tax", "total"]
            rows = [[f"{r['bp'] / 100:g}%" + (" incl." if r["inc"] else ""), r["t"] - r["tx"], r["tx"], r["t"]]
                    for r in self.c.execute(
                f"SELECT l.tax_bp bp, l.tax_inclusive inc, SUM(l.line_tax) tx, SUM(l.line_total) t FROM sale_lines l"
                f" JOIN sales s ON s.id=l.sale_id WHERE {_DONE}{cash} GROUP BY l.tax_bp, l.tax_inclusive ORDER BY bp", args)]
            return cols, rows, self._totals(rows, 1)
        raise InvalidInput(f"unknown report {kind}")

    @staticmethod
    def _totals(rows: list[list], first_numeric: int) -> list:
        if not rows:
            return []
        out: list = ["TOTAL"]
        for i in range(1, len(rows[0])):
            vals = [r[i] for r in rows]
            out.append(sum(vals) if all(isinstance(v, (int, float)) for v in vals) else "")
        return out
