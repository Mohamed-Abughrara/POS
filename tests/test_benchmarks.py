"""NFR-01..03 performance checks (run with: pytest -m benchmark)."""
import statistics
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from pos.application.dto import (CompleteSaleInput, OpenShiftInput, PaymentInput, ReportInput, ScanItemInput)
from pos.domain.barcode import check_digit
from tests.conftest import build_app

pytestmark = pytest.mark.benchmark


def _bulk_products(conn, n):
    rows = []
    for i in range(n):
        body = f"6230{i:08d}"
        rows.append((uuid.uuid4().hex, f"SKU{i:06d}", body + str(check_digit(body)), "صنف", f"Item {i}", 1000 + i % 500))
    conn.execute("BEGIN")
    conn.executemany("INSERT INTO products(id,sku,barcode,name_ar,name_en,price) VALUES(?,?,?,?,?,?)", rows)
    conn.execute("COMMIT")
    return rows


def test_scan_to_display_p95_under_200ms(tmp_path):
    app = build_app(tmp_path, str(tmp_path / "bench.db"))
    rows = _bulk_products(app.conn, 20_000)
    app.shifts.open_shift(OpenShiftInput(app.cashier_id, 0))
    sale_id, times = None, []
    for i in range(200):
        t0 = time.perf_counter()
        cart = app.checkout.scan_item(ScanItemInput(app.cashier_id, sale_id, rows[(i * 97) % len(rows)][2]))
        times.append((time.perf_counter() - t0) * 1000)
        sale_id = cart.sale_id
    p95 = sorted(times)[int(len(times) * 0.95)]
    print(f"scan p95={p95:.1f}ms median={statistics.median(times):.1f}ms")
    assert p95 <= 200


def test_sale_completion_and_daily_report(tmp_path):
    app = build_app(tmp_path, str(tmp_path / "bench2.db"))
    app.shifts.open_shift(OpenShiftInput(app.cashier_id, 0))
    cart = app.checkout.scan_item(ScanItemInput(app.cashier_id, None, app.cola, Decimal(3)))
    t0 = time.perf_counter()
    app.checkout.complete_sale(CompleteSaleInput(app.cashier_id, cart.sale_id, [PaymentInput("CASH", cart.total)]))
    assert time.perf_counter() - t0 <= 1.0                                   # NFR-02

    # 1,500 sales on one day, inserted directly for speed
    shift = app.conn.execute("SELECT id FROM shifts").fetchone()["id"]
    day = datetime(2026, 11, 9, 12, 0, 0).isoformat()
    app.conn.execute("BEGIN")
    for n in range(2, 1502):
        sid = uuid.uuid4().hex
        app.conn.execute("INSERT INTO sales(id,number,shift_id,cashier_id,status,created_at,completed_at,subtotal,"
                         "discount_total,tax_total,total) VALUES(?,?,?,?,'COMPLETED',?,?,4500,0,0,4500)",
                         (sid, n, shift, app.cashier_id, day, day))
        app.conn.execute("INSERT INTO payments(sale_id,method,amount) VALUES(?,'CASH',4500)", (sid,))
        app.conn.execute("INSERT INTO sale_lines(sale_id,line_no,product_id,name,name_ar,unit_price,qty_milli,unit,"
                         "tax_bp,tax_inclusive,line_tax,line_total) SELECT ?,1,id,'Cola','x',1500,3000,'PIECE',0,0,0,4500 "
                         "FROM products WHERE sku='COLA'", (sid,))
    app.conn.execute("COMMIT")
    d = datetime(2026, 11, 9).date()
    for kind in ("DAILY", "BY_PRODUCT", "BY_CASHIER", "BY_PAYMENT", "TAX"):
        t0 = time.perf_counter()
        app.reports.generate(ReportInput(app.manager_id, kind, d, d))
        elapsed = time.perf_counter() - t0
        print(f"{kind}: {elapsed * 1000:.0f}ms")
        assert elapsed <= 3.0                                                # NFR-03
