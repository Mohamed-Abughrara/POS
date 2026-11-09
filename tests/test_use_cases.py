import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from pos.application.dto import (AdjustStockInput, ApplyDiscountInput, ApproverCredentials, CloseShiftInput,
                                 CompleteSaleInput, EditCartInput, OpenShiftInput, PaymentInput, ProductView,
                                 RefundInput, ReportInput, ScanItemInput, UserInput)
from pos.application.errors import *  # noqa: F403
from pos.domain.errors import *       # noqa: F403
from pos.infrastructure.printing.printers import NullPrinter


def open_shift(app, float_=10_000):
    return app.shifts.open_shift(OpenShiftInput(app.cashier_id, float_))


def scan(app, code, sale_id=None, qty=1):
    return app.checkout.scan_item(ScanItemInput(app.cashier_id, sale_id, code, Decimal(qty)))


def pay_cash(app, sale_id, amount, tendered=None):
    return app.checkout.complete_sale(CompleteSaleInput(app.cashier_id, sale_id, [PaymentInput("CASH", amount, tendered)]))


def sell_cola(app, n=2):
    cart = scan(app, app.cola, qty=n)
    return pay_cash(app, cart.sale_id, cart.total)


# ---- auth -----------------------------------------------------------------
def test_login_password_pin_and_failures(app):
    assert app.auth.login("cashier", "cashier1").role == "CASHIER"
    assert app.auth.login("cashier", "1234").username == "cashier"        # PIN
    with pytest.raises(AuthenticationFailed):
        app.auth.login("cashier", "wrong")
    with pytest.raises(AuthenticationFailed):
        app.auth.login("nobody", "x")
    app.auth.lock(app.cashier_id)
    assert app.auth.unlock(app.cashier_id, "1234")
    with pytest.raises(AuthenticationFailed):
        app.auth.unlock(app.cashier_id, "bad")
    actions = [e.action for e in app.uow().__enter__().audit.recent(50)]
    assert "LOGIN_FAILED" in actions and "UNLOCK" in actions


# ---- checkout -----------------------------------------------------------------
def test_scan_requires_open_shift(app):
    with pytest.raises(ShiftNotOpen):
        scan(app, app.cola)


def test_full_sale_flow_stock_receipt_and_drawer(app):
    open_shift(app)
    cart = scan(app, app.cola, qty=2)
    cart = scan(app, "RICE", cart.sale_id, qty=1)          # SKU lookup, 1 piece of KG item -> 1 kg
    assert cart.total == 3000 + 2625                        # 5% exclusive tax on rice
    receipt = pay_cash(app, cart.sale_id, cart.total, tendered=6000)
    assert receipt.number == 1 and receipt.change_due == 6000 - 5625 and receipt.printed
    assert app.printer.drawer_kicks >= 2                    # shift open + cash sale
    assert len(app.printer.documents) == 1
    with app.uow() as u:
        cola = u.products.get_by_barcode(app.cola)
        assert u.stock.on_hand(cola.id) == Decimal(98)
        assert u.sales.get(cart.sale_id).status.value == "COMPLETED"


def test_unknown_item_and_inactive_product(app):
    open_shift(app)
    with pytest.raises(ProductNotFound):
        scan(app, "0000")
    with app.uow() as u:
        pid = u.products.get_by_barcode(app.cola).id
    app.catalogue.set_product_active(app.manager_id, pid, False)
    with pytest.raises(ProductInactive):
        scan(app, app.cola)


def test_edit_cart_and_void(app):
    open_shift(app)
    cart = scan(app, app.cola, qty=3)
    cart = app.checkout.edit_cart(EditCartInput(app.cashier_id, cart.sale_id, "SET_QTY", 1, Decimal(1)))
    assert cart.total == 1500
    cart = app.checkout.edit_cart(EditCartInput(app.cashier_id, cart.sale_id, "REMOVE", 1))
    assert cart.lines == []
    cart = scan(app, app.cola, cart.sale_id)
    app.checkout.edit_cart(EditCartInput(app.cashier_id, cart.sale_id, "VOID"))
    with pytest.raises(SaleNotEditable):
        scan(app, app.cola, cart.sale_id)


def test_discount_limit_and_approval(app):
    open_shift(app)
    cart = scan(app, app.cola, qty=2)                       # 3000
    small = app.checkout.apply_discount(ApplyDiscountInput(app.cashier_id, cart.sale_id, "CART", "PERCENT", Decimal(10)))
    assert small.total == 2700
    with pytest.raises(DiscountLimitExceeded):
        app.checkout.apply_discount(ApplyDiscountInput(app.cashier_id, cart.sale_id, "CART", "PERCENT", Decimal(30)))
    with pytest.raises(ApprovalRejected):
        app.checkout.apply_discount(ApplyDiscountInput(app.cashier_id, cart.sale_id, "CART", "PERCENT", Decimal(30),
                                                       approver_credentials=ApproverCredentials("cashier", "cashier1")))
    with pytest.raises(ApprovalRejected):
        app.checkout.apply_discount(ApplyDiscountInput(app.cashier_id, cart.sale_id, "CART", "PERCENT", Decimal(30),
                                                       approver_credentials=ApproverCredentials("manager", "nope")))
    big = app.checkout.apply_discount(ApplyDiscountInput(app.cashier_id, cart.sale_id, "CART", "PERCENT", Decimal(30),
                                                         approver_credentials=ApproverCredentials("manager", "4321")))
    assert big.total == 2100
    with pytest.raises(InvalidDiscount):
        app.checkout.apply_discount(ApplyDiscountInput(app.cashier_id, cart.sale_id, "LINE", "FIXED", Decimal(99999), 1))
    line = app.checkout.apply_discount(ApplyDiscountInput(app.cashier_id, cart.sale_id, "LINE", "FIXED", Decimal(100), 1))
    assert line.lines[0].line_discount > 0


def test_payment_errors_and_split(app):
    open_shift(app)
    cart = scan(app, app.cola, qty=2)                       # 3000
    with pytest.raises(InsufficientPayment):
        pay_cash(app, cart.sale_id, 1000)
    with pytest.raises(CardReferenceMissing):
        app.checkout.complete_sale(CompleteSaleInput(app.cashier_id, cart.sale_id, [PaymentInput("CARD", 3000)]))
    receipt = app.checkout.complete_sale(CompleteSaleInput(app.cashier_id, cart.sale_id, [
        PaymentInput("CASH", 1000, 1000), PaymentInput("CARD", 2000, None, "AUTH-9")]))
    assert receipt.change_due == 0 and len(receipt.payments) == 2
    with pytest.raises(SaleNotEditable):
        pay_cash(app, cart.sale_id, 3000)


def test_sale_transaction_rolls_back_on_failure(app):
    open_shift(app)
    cart = scan(app, app.cola)
    with pytest.raises(InsufficientPayment):
        pay_cash(app, cart.sale_id, 1)
    with app.uow() as u:
        assert u.sales.get(cart.sale_id).status.value == "DRAFT"      # nothing half-written
        assert u.sales.find_by_number(1) is None


def test_printer_failure_never_blocks_sale(app):
    open_shift(app)
    app.printer.fail = True
    receipt = sell_cola(app)
    assert receipt.printed is False and receipt.number == 1
    app.printer.fail = False
    again = app.checkout.reprint_receipt(app.cashier_id, 1)
    assert again.printed and len(app.printer.documents) == 1
    with pytest.raises(SaleNotFound):
        app.checkout.reprint_receipt(app.cashier_id, 99)


def test_park_and_recall(app):
    open_shift(app)
    cart = scan(app, app.cola)
    app.checkout.park_sale(app.cashier_id, cart.sale_id)
    assert [p.sale_id for p in app.checkout.list_parked(app.cashier_id)] == [cart.sale_id]
    with pytest.raises(SaleNotEditable):
        scan(app, app.cola, cart.sale_id)
    recalled = app.checkout.recall_sale(app.cashier_id, cart.sale_id)
    assert recalled.status == "DRAFT" and app.checkout.get_cart(app.cashier_id, cart.sale_id).total == 1500


def test_completed_sale_is_immutable_in_db(app):
    open_shift(app)
    receipt = sell_cola(app)
    with pytest.raises(sqlite3.DatabaseError):
        app.conn.execute("UPDATE sales SET total = 1 WHERE id = ?", (receipt.sale_id,))
    with pytest.raises(sqlite3.DatabaseError):
        app.conn.execute("DELETE FROM sale_lines WHERE sale_id = ?", (receipt.sale_id,))
    with pytest.raises(sqlite3.DatabaseError):
        app.conn.execute("UPDATE audit_log SET action='x'")
    with pytest.raises(sqlite3.DatabaseError):
        app.conn.execute("DELETE FROM stock_movements")


# ---- refunds ----------------------------------------------------------------------
def test_refund_flow_with_approval_and_limits(app):
    open_shift(app)
    receipt = sell_cola(app, 3)                               # 4500
    view = app.refunds.lookup(app.cashier_id, receipt.number)
    assert view.lines[0].remaining == 3
    with pytest.raises(ApprovalRequired):
        app.refunds.process_refund(RefundInput(app.cashier_id, 1, [(1, Decimal(1))], "CASH", "damaged"))
    with pytest.raises(ApprovalRejected):
        app.refunds.process_refund(RefundInput(app.cashier_id, 1, [(1, Decimal(1))], "CASH", "x",
                                               ApproverCredentials("manager", "bad")))
    r = app.refunds.process_refund(RefundInput(app.cashier_id, 1, [(1, Decimal(1))], "CASH", "damaged",
                                               ApproverCredentials("manager", "manager1")))
    assert r.amount == 1500 and r.number == 1
    with pytest.raises(RefundExceedsSold):
        app.refunds.process_refund(RefundInput(app.cashier_id, 1, [(1, Decimal(3))], "CASH", "x",
                                               ApproverCredentials("manager", "manager1")))
    r2 = app.refunds.process_refund(RefundInput(app.cashier_id, 1, [(1, Decimal(2))], "CARD", "rest",
                                                ApproverCredentials("manager", "manager1")))
    assert r2.amount == 3000
    with app.uow() as u:
        assert u.stock.on_hand(u.products.get_by_barcode(app.cola).id) == Decimal(100)   # fully restocked
    with pytest.raises(SaleNotFound):
        app.refunds.process_refund(RefundInput(app.cashier_id, 77, [(1, Decimal(1))], "CASH", "x",
                                               ApproverCredentials("manager", "manager1")))
    assert app.refunds.lookup(app.cashier_id, 1).lines[0].remaining == 0


# ---- shifts -------------------------------------------------------------------------
def test_shift_open_close_z_report(app):
    shift = open_shift(app, 10_000)
    with pytest.raises(ShiftAlreadyOpen):
        open_shift(app)
    sell_cola(app, 2)                                         # +3000 cash
    app.checkout.complete_sale  # noqa: B018
    cart = scan(app, app.cola)
    app.checkout.complete_sale(CompleteSaleInput(app.cashier_id, cart.sale_id, [PaymentInput("CARD", 1500, None, "R1")]))
    app.refunds.process_refund(RefundInput(app.cashier_id, 1, [(1, Decimal(1))], "CASH", "r",
                                           ApproverCredentials("manager", "manager1")))   # -1500 cash
    z = app.shifts.close_shift(CloseShiftInput(app.cashier_id, shift.shift_id, 11_500))
    assert z.expected_cash == 10_000 + 3000 - 1500 and z.variance == 0
    assert z.sales_count == 2 and z.gross == 4500 and z.refunds == 1500 and z.net == 3000
    assert z.by_method == {"CASH": 3000, "CARD": 1500}
    with pytest.raises(ShiftNotOpen):
        app.shifts.close_shift(CloseShiftInput(app.cashier_id, shift.shift_id, 0))
    with pytest.raises(ShiftNotOpen):
        scan(app, app.cola)


def test_close_shift_variance_needs_approval_and_parked_blocks(app):
    shift = open_shift(app, 10_000)
    with pytest.raises(ApprovalRequired):
        app.shifts.close_shift(CloseShiftInput(app.cashier_id, shift.shift_id, 1000))      # 9 LYD short
    cart = scan(app, app.cola)
    app.checkout.park_sale(app.cashier_id, cart.sale_id)
    with pytest.raises(ParkedSalesExist):
        app.shifts.close_shift(CloseShiftInput(app.cashier_id, shift.shift_id, 10_000))
    with pytest.raises(ApprovalRequired):
        app.shifts.close_shift(CloseShiftInput(app.cashier_id, shift.shift_id, 10_000, force_void_parked=True))
    z = app.shifts.close_shift(CloseShiftInput(app.cashier_id, shift.shift_id, 9000, force_void_parked=True,
                                               approver_credentials=ApproverCredentials("manager", "manager1")))
    assert z.variance == -1000
    with app.uow() as u:
        assert u.sales.get(cart.sale_id).status.value == "VOIDED"


# ---- catalogue / stock -------------------------------------------------------------------
def test_catalogue_permissions_duplicates_and_audit(app):
    view = ProductView(None, "NEW", None, "ج", "New", None, 500)
    with pytest.raises(PermissionDenied):
        app.catalogue.save_product(app.cashier_id, view)
    saved = app.catalogue.save_product(app.manager_id, view)
    with pytest.raises(DuplicateEntity):
        app.catalogue.save_product(app.manager_id, ProductView(None, "NEW", None, "x", "x", None, 1))
    with pytest.raises(DuplicateEntity):
        app.catalogue.save_product(app.manager_id, ProductView(None, "N2", app.cola, "x", "x", None, 1))
    with pytest.raises(InvalidBarcode):
        app.catalogue.save_product(app.manager_id, ProductView(None, "N3", "123", "x", "x", None, 1))
    from dataclasses import replace
    app.catalogue.save_product(app.manager_id, replace(saved, price=700))
    with app.uow() as u:
        assert "PRICE_CHANGE" in [e.action for e in u.audit.recent(20)]
    assert any(p.sku == "NEW" for p in app.catalogue.search_products(app.cashier_id, "ne"))


def test_customers(app):
    from pos.application.dto import CustomerView
    c = app.catalogue.save_customer(app.cashier_id, CustomerView(None, "Ali", "0910000000", "L1"))
    with pytest.raises(DuplicateEntity):
        app.catalogue.save_customer(app.cashier_id, CustomerView(None, "Other", "0910000000"))
    assert app.catalogue.search_customers(app.cashier_id, "Ali")[0].id == c.id
    open_shift(app)
    cart = scan(app, app.cola)
    r = app.checkout.complete_sale(CompleteSaleInput(app.cashier_id, cart.sale_id, [PaymentInput("CASH", 1500)], c.id))
    assert r.customer_name == "Ali"


def test_stock_adjustments_and_low_stock(app):
    with app.uow() as u:
        pid = u.products.get_by_barcode(app.cola).id
    lvl = app.catalogue.adjust_stock(AdjustStockInput(app.manager_id, pid, "WASTE", Decimal(97), "spoiled"))
    assert lvl.on_hand == 3 and lvl.below_reorder                  # reorder level 5
    assert [p.sku for p in app.catalogue.low_stock(app.manager_id)] == ["COLA"]
    assert app.catalogue.adjust_stock(AdjustStockInput(app.manager_id, pid, "ADJUSTMENT", Decimal(-1))).on_hand == 2
    with pytest.raises(PermissionDenied):
        app.catalogue.adjust_stock(AdjustStockInput(app.cashier_id, pid, "RECEIPT", Decimal(1)))
    with pytest.raises(InvalidQuantity):
        app.catalogue.adjust_stock(AdjustStockInput(app.manager_id, pid, "RECEIPT", Decimal(0)))
    with pytest.raises(InvalidQuantity):
        app.catalogue.adjust_stock(AdjustStockInput(app.manager_id, pid, "SALE", Decimal(1)))
    with pytest.raises(ProductNotFound):
        app.catalogue.adjust_stock(AdjustStockInput(app.manager_id, "nope", "RECEIPT", Decimal(1)))


# ---- reports --------------------------------------------------------------------------------
def test_reports_and_csv(app, tmp_path):
    open_shift(app)
    sell_cola(app, 2)
    cart = scan(app, "RICE")
    pay_cash(app, cart.sale_id, cart.total)
    today = app.clock.t.date()
    base = dict(actor_id=app.manager_id, date_from=today, date_to=today)
    daily = app.reports.generate(ReportInput(kind="DAILY", **base))
    assert daily.rows[0][1] == 2 and daily.rows[0][2] == 3000 + 2625
    by_product = app.reports.generate(ReportInput(kind="BY_PRODUCT", **base))
    assert {r[0] for r in by_product.rows} == {"Cola", "Rice"}
    assert app.reports.generate(ReportInput(kind="BY_CASHIER", **base)).rows[0][1] == 2
    assert app.reports.generate(ReportInput(kind="BY_PAYMENT", **base)).rows[0][2] == 5625
    tax = app.reports.generate(ReportInput(kind="TAX", **base))
    assert sum(r[2] for r in tax.rows) == 125
    out = app.reports.export_csv(ReportInput(kind="DAILY", **base), tmp_path / "x" / "daily.csv")
    assert out.read_text(encoding="utf-8-sig").startswith("date,count")
    with pytest.raises(PermissionDenied):
        app.reports.generate(ReportInput(actor_id=app.cashier_id, kind="DAILY", date_from=today, date_to=today))
    with pytest.raises(InvalidDateRange):
        app.reports.generate(ReportInput(app.manager_id, "DAILY", date(2026, 12, 1), date(2026, 11, 1)))
    with pytest.raises(InvalidInput):
        app.reports.generate(ReportInput(app.manager_id, "NOPE", today, today))
    assert app.reports.generate(ReportInput(app.manager_id, "DAILY", date(2000, 1, 1), date(2000, 1, 2))).rows == []


# ---- admin ------------------------------------------------------------------------------------
def test_admin_users_settings_backup_restore(app, tmp_path):
    with pytest.raises(PermissionDenied):
        app.admin.list_users(app.manager_id)
    with pytest.raises(DuplicateEntity):
        app.admin.save_user(app.admin_id, UserInput(None, "cashier", "x", "CASHIER", password="abcdef"))
    with pytest.raises(InvalidInput):
        app.admin.save_user(app.admin_id, UserInput(None, "n", "x", "CASHIER", password="abc"))
    with pytest.raises(InvalidInput):
        app.admin.save_user(app.admin_id, UserInput(None, "n", "x", "CASHIER", password="abcdef", pin="12"))
    with pytest.raises(InvalidInput):          # last admin protected
        app.admin.save_user(app.admin_id, UserInput(app.admin_id, "admin", "A", "CASHIER"))
    app.admin.save_user(app.admin_id, UserInput(app.cashier_id, "cashier", "Cashier 2", "CASHIER", "ar", False))
    with pytest.raises(AuthenticationFailed):
        app.auth.login("cashier", "cashier1")
    app.admin.save_settings(app.admin_id, {"store_name": "My Shop"})
    assert app.admin.get_settings(app.cashier_id)["store_name"] == "My Shop"
    with pytest.raises(PermissionDenied):
        app.admin.save_settings(app.manager_id, {"a": "b"})

    info = app.admin.backup_now(app.admin_id)
    assert info.size_bytes > 0 and len(app.admin.list_backups(app.admin_id)) == 1
    app.admin.save_settings(app.admin_id, {"store_name": "Changed"})
    app.admin.restore(app.admin_id, __import__("pathlib").Path(info.path))
    assert app.admin.get_settings(app.admin_id)["store_name"] == "My Shop"
    with pytest.raises(BackupError):
        app.admin.restore(app.admin_id, tmp_path / "missing.db")
    bogus = tmp_path / "bogus.db"
    bogus.write_text("not a database")
    with pytest.raises(BackupError):
        app.admin.restore(app.admin_id, bogus)
    app.admin.set_locale(app.manager_id, "ar")


def test_seed_is_idempotent(app):
    from pos.application.use_cases.admin import SeedDefaults
    from pos.infrastructure.system import UuidGenerator
    assert SeedDefaults(app.uow, app.clock, UuidGenerator(), app.hasher).run() is False
