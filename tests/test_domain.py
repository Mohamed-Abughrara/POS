from datetime import datetime
from decimal import Decimal

import pytest

from pos.domain.barcode import Barcode, check_digit
from pos.domain.discount import Discount, DiscountKind
from pos.domain.entities import Product, Role, Shift
from pos.domain.errors import *  # noqa: F403
from pos.domain.money import Money, round_half_up_div
from pos.domain.quantity import Quantity, Unit
from pos.domain.refund import Refund
from pos.domain.sale import Payment, PaymentMethod, Sale, SaleStatus
from pos.domain.tax import TaxRate

NOW = datetime(2026, 11, 9, 10, 0)


def product(price=1000, bp=0, inclusive=False, unit=Unit.PIECE, active=True, id="p1"):
    return Product(id, "SKU" + id, "س", "Item", Money(price), tax_rate=TaxRate(bp, inclusive),
                   unit=unit, is_active=active)


def sale():
    return Sale("s1", "sh1", "u1", NOW)


def test_money_integer_only_and_currency():
    with pytest.raises(InvalidAmount):
        Money(1.5)
    with pytest.raises(InvalidAmount):
        Money(True)
    with pytest.raises(CurrencyMismatch):
        Money(1) + Money(1, "USD")
    assert (Money(5) - Money(7)).amount == -2


def test_rounding_half_up_and_allocate():
    assert round_half_up_div(5, 2) == 3 and round_half_up_div(-5, 2) == -3 and round_half_up_div(4, 3) == 1
    parts = Money(100).allocate([1, 1, 1])
    assert [p.amount for p in parts] == [34, 33, 33] and sum(p.amount for p in parts) == 100
    assert [p.amount for p in Money(10).allocate([0, 0])] == [0, 0]
    with pytest.raises(InvalidAmount):
        Money(1).allocate([])


def test_quantity_rules():
    with pytest.raises(InvalidQuantity):
        Quantity(Decimal("1.5"))
    with pytest.raises(InvalidQuantity):
        Quantity(Decimal(0))
    with pytest.raises(InvalidQuantity):
        Quantity(Decimal("1.2345"), Unit.KG)
    assert (Quantity(Decimal("1.250"), Unit.KG) + Quantity(Decimal("0.750"), Unit.KG)).value == Decimal("2")
    with pytest.raises(InvalidQuantity):
        Quantity(Decimal(1)) + Quantity(Decimal(1), Unit.KG)


def test_barcode_checksum():
    body = "622000000001"
    assert Barcode(body + str(check_digit(body))).value
    with pytest.raises(InvalidBarcode):
        Barcode("6220000000019" if check_digit(body) != 9 else "6220000000010")
    assert Barcode("2000000000123")        # internal prefix 2: no checksum
    with pytest.raises(InvalidBarcode):
        Barcode("12345")
    with pytest.raises(InvalidBarcode):
        Barcode("abc")


def test_tax_exclusive_and_inclusive():
    assert TaxRate(500).tax_on(Money(1000)).amount == 50 and TaxRate(500).payable(Money(1000)).amount == 1050
    inc = TaxRate(500, True)
    assert inc.tax_on(Money(1050)).amount == 50 and inc.payable(Money(1050)).amount == 1050
    assert TaxRate(0).tax_on(Money(1000)).amount == 0
    with pytest.raises(InvalidTaxRate):
        TaxRate(10_001)


def test_discount_rules():
    assert Discount(DiscountKind.PERCENT, Decimal(10)).amount_for(Money(1500)).amount == 150
    assert Discount(DiscountKind.FIXED, Decimal(200)).amount_for(Money(1500)).amount == 200
    with pytest.raises(InvalidDiscount):
        Discount(DiscountKind.PERCENT, Decimal(101))
    with pytest.raises(InvalidDiscount):
        Discount(DiscountKind.FIXED, Decimal("1.5"))
    with pytest.raises(InvalidDiscount):
        Discount(DiscountKind.FIXED, Decimal(2000)).amount_for(Money(1500))
    assert Discount(DiscountKind.FIXED, Decimal(150)).percent_of(Money(1500)) == 10


def test_product_validation():
    with pytest.raises(InvalidAmount):
        product(price=-1)
    with pytest.raises(InvalidBarcode):
        Product("x", "S", "a", "b", Money(1), barcode="123")


def test_sale_totals_with_discounts_and_tax():
    s = sale()
    s.add_item(product(1000, 500), Quantity(Decimal(2)))            # 2000 + 5% = 2100
    s.add_item(product(1500, id="p2"), Quantity(Decimal(1)))        # 1500, no tax
    s.apply_line_discount(2, Discount(DiscountKind.FIXED, Decimal(500)))   # line 2 net 1000
    s.apply_cart_discount(Discount(DiscountKind.PERCENT, Decimal(10)))     # 10% of 3000 = 300
    t = s.totals()
    assert t.subtotal.amount == 3500
    assert t.discount_total.amount == 800
    # cart discount 300 split 2000:1000 -> 200 / 100; taxed line: (2000-200)*5% = 90
    assert t.tax_total.amount == 90
    assert t.total.amount == (1800 + 90) + 900


def test_sale_merge_and_edit_rules():
    s = sale()
    p = product()
    s.add_item(p, Quantity(Decimal(1)))
    s.add_item(p, Quantity(Decimal(2)))
    assert len(s.lines) == 1 and s.lines[0].quantity.value == 3
    with pytest.raises(ProductInactive):
        s.add_item(product(active=False, id="p9"), Quantity(Decimal(1)))
    with pytest.raises(InvalidQuantity):
        s.add_item(product(unit=Unit.KG, id="p8"), Quantity(Decimal(1)))     # unit mismatch
    s.set_quantity(1, Quantity(Decimal(1)))
    s.remove_line(1)
    assert not s.lines


def test_payment_rules_and_completion():
    s = sale()
    s.add_item(product(1000), Quantity(Decimal(1)))
    with pytest.raises(InsufficientPayment):
        s.complete(NOW)
    with pytest.raises(CardReferenceMissing):
        Payment(PaymentMethod.CARD, Money(100))
    with pytest.raises(InvalidAmount):
        Payment(PaymentMethod.CASH, Money(0))
    with pytest.raises(InvalidAmount):
        Payment(PaymentMethod.CASH, Money(500), Money(100))
    s.add_payment(Payment(PaymentMethod.CASH, Money(400), Money(500)))
    assert s.balance_due.amount == 600 and s.change_due.amount == 100
    s.add_payment(Payment(PaymentMethod.CARD, Money(600), None, "REF1"))
    s.complete(NOW)
    assert s.status == SaleStatus.COMPLETED
    with pytest.raises(SaleNotEditable):
        s.add_item(product(), Quantity(Decimal(1)))
    with pytest.raises(SaleNotEditable):
        s.add_payment(Payment(PaymentMethod.CASH, Money(1)))


def test_park_recall_void():
    s = sale()
    with pytest.raises(InvalidEntity):
        s.park()
    s.add_item(product(), Quantity(Decimal(1)))
    s.park()
    with pytest.raises(SaleNotEditable):
        s.add_item(product(), Quantity(Decimal(1)))
    s.recall()
    assert s.status == SaleStatus.DRAFT
    s.void()
    with pytest.raises(SaleNotEditable):
        s.void()


def test_refund_limits_and_rounding_absorption():
    s = sale()
    s.add_item(product(1000, 500), Quantity(Decimal(3)))     # 3150 total
    s.add_payment(Payment(PaymentMethod.CASH, Money(3150)))
    s.complete(NOW)
    kw = dict(original=s, shift_id="sh", method=PaymentMethod.CASH, approved_by="m", reason="r", created_at=NOW)
    r1 = Refund.build(id="r1", requested=[(1, Decimal(1))], already_refunded={}, **kw)
    assert r1.amount.amount == 1050
    r2 = Refund.build(id="r2", requested=[(1, Decimal(2))], already_refunded={1: (Decimal(1), r1.amount)}, **kw)
    assert r2.amount.amount == 2100                               # last refund absorbs remainder
    with pytest.raises(RefundExceedsSold):
        Refund.build(id="r3", requested=[(1, Decimal(3))], already_refunded={1: (Decimal(1), r1.amount)}, **kw)
    with pytest.raises(InvalidQuantity):
        Refund.build(id="r4", requested=[], already_refunded={}, **kw)
    with pytest.raises(SaleNotRefundable):
        Refund.build(id="r5", requested=[(9, Decimal(1))], already_refunded={}, **kw)
    draft = sale()
    with pytest.raises(SaleNotRefundable):
        Refund.build(id="r6", original=draft, shift_id="sh", requested=[(1, Decimal(1))], already_refunded={},
                     method=PaymentMethod.CASH, approved_by="m", reason="", created_at=NOW)


def test_shift_variance_and_roles():
    sh = Shift("s", "u", NOW, Money(10_000))
    sh.close(Money(9_500), Money(10_000), NOW)
    assert sh.variance.amount == -500 and not sh.is_open
    with pytest.raises(ShiftNotOpen):
        sh.close(Money(0), Money(0), NOW)
    assert Role.MANAGER.at_least(Role.CASHIER) and not Role.CASHIER.at_least(Role.MANAGER)
