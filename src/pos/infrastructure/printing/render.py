"""Plain-text rendering of receipts, refund slips and Z-reports (bilingual labels)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ...application.dto import RefundReceipt, SaleReceipt, ZReport


def money(dirhams: int) -> str:
    sign = "-" if dirhams < 0 else ""
    d = abs(dirhams)
    return f"{sign}{d // 1000}.{d % 1000:03d}"


def qty(q: Decimal) -> str:
    return str(int(q)) if q == q.to_integral_value() else f"{q:.3f}"


def _row(left: str, right: str, width: int) -> str:
    space = max(1, width - len(left) - len(right))
    return left + " " * space + right


def _center(text: str, width: int) -> str:
    return text.center(width).rstrip()


def render_document(doc: Any, width: int = 42) -> str:
    line = "-" * width
    out: list[str] = [_center(h, width) for h in getattr(doc, "header", [])]
    if isinstance(doc, SaleReceipt):
        out += [line, _row(f"Receipt / فاتورة #{doc.number:06d}", "", width),
                _row(doc.created_at.strftime("%Y-%m-%d %H:%M"), doc.cashier_name, width)]
        if doc.customer_name:
            out.append(f"Customer / العميل: {doc.customer_name}")
        out.append(line)
        for l in doc.lines:
            out.append(l.name or l.name_ar)
            out.append(_row(f"  {qty(l.quantity)} x {money(l.unit_price)}", money(l.total), width))
        out.append(line)
        out.append(_row("Subtotal / المجموع", money(doc.subtotal), width))
        if doc.discount_total:
            out.append(_row("Discount / الخصم", "-" + money(doc.discount_total), width))
        if doc.tax_total:
            out.append(_row("Tax / الضريبة", money(doc.tax_total), width))
        out.append(_row("TOTAL / الإجمالي", money(doc.total), width))
        out.append(line)
        for p in doc.payments:
            label = "Cash / نقدي" if p.method == "CASH" else f"Card / بطاقة {p.reference or ''}".strip()
            out.append(_row(label, money(p.tendered if p.tendered else p.amount), width))
        if doc.change_due:
            out.append(_row("Change / الباقي", money(doc.change_due), width))
    elif isinstance(doc, RefundReceipt):
        out += [line, f"REFUND / مرتجع #{doc.number:06d}  (receipt {doc.original_no:06d})",
                doc.created_at.strftime("%Y-%m-%d %H:%M"), line]
        for l in doc.lines:
            out.append(_row(f"{l.name} x{qty(l.quantity)}", money(l.total), width))
        out += [line, _row("REFUND TOTAL / إجمالي المرتجع", money(doc.amount), width),
                f"Method: {doc.method}", f"Reason: {doc.reason}"]
    elif isinstance(doc, ZReport):
        out += [line, _center("Z-REPORT / تقرير الإغلاق", width), line,
                _row("Cashier / الكاشير", doc.cashier_name, width),
                _row("Opened / فتح", doc.opened_at.strftime("%Y-%m-%d %H:%M"), width),
                _row("Closed / أغلق", doc.closed_at.strftime("%Y-%m-%d %H:%M"), width), line,
                _row("Sales / المبيعات", str(doc.sales_count), width),
                _row("Gross / الإجمالي", money(doc.gross), width),
                _row("Discounts / الخصومات", money(doc.discounts), width),
                _row("Tax / الضريبة", money(doc.tax), width),
                _row("Refunds / المرتجعات", money(doc.refunds), width),
                _row("NET / الصافي", money(doc.net), width), line]
        for method, amount in sorted(doc.by_method.items()):
            out.append(_row(method, money(amount), width))
        out += [line, _row("Opening float / العهدة", money(doc.opening_float), width),
                _row("Expected cash / المتوقع", money(doc.expected_cash), width),
                _row("Counted cash / المعدود", money(doc.counted_cash), width),
                _row("VARIANCE / الفرق", money(doc.variance), width)]
    else:
        raise TypeError(f"cannot print {type(doc).__name__}")
    if getattr(doc, "footer", ""):
        out += [line, _center(doc.footer, width)]
    return "\n".join(out) + "\n"
