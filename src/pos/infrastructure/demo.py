"""Optional demo data (`python main.py --demo`): extra users, categories and sample products."""
from __future__ import annotations

from decimal import Decimal

from ..application.dto import AdjustStockInput, CategoryView, ProductView, UserInput
from ..domain.barcode import check_digit


def ean13(body12: str) -> str:
    return body12 + str(check_digit(body12))


def seed_demo(admin_uc, catalogue_uc, admin_id: str) -> None:
    users = {u.username for u in admin_uc.list_users(admin_id)}
    if "manager" not in users:
        admin_uc.save_user(admin_id, UserInput(None, "manager", "Demo Manager", "MANAGER", "en",
                                               password="manager123", pin="4321"))
    if "cashier" not in users:
        admin_uc.save_user(admin_id, UserInput(None, "cashier", "Demo Cashier", "CASHIER", "ar",
                                               password="cashier123", pin="1234"))
    if catalogue_uc.search_products(admin_id, "", True, 1):
        return
    cats = {c.name_en: c for c in catalogue_uc.list_categories(admin_id)}
    general = cats.get("General")
    food = catalogue_uc.save_category(admin_id, CategoryView(None, "مواد غذائية", "Groceries", 0, False))
    goods = catalogue_uc.save_category(admin_id, CategoryView(None, "سلع عامة", "Household", 500, False))
    samples = [
        ("COLA330", "622100000001", "كولا 330 مل", "Cola 330ml", food.id, 750, 450, "PIECE", 24),
        ("WATER15", "622100000002", "مياه 1.5 لتر", "Water 1.5L", food.id, 500, 250, "PIECE", 24),
        ("BREAD", "622100000003", "خبز", "Bread loaf", food.id, 300, 150, "PIECE", 10),
        ("RICE", "622100000004", "أرز (كجم)", "Rice (per kg)", food.id, 2400, 1700, "KG", 5),
        ("SOAP", "622100000005", "صابون", "Soap bar", goods.id, 1250, 700, "PIECE", 10),
        ("BAG", "622100000006", "كيس قماش", "Cloth bag", (general.id if general else goods.id), 2000, 900, "PIECE", 3),
    ]
    for sku, body, ar, en, cat_id, price, cost, unit, reorder in samples:
        p = catalogue_uc.save_product(admin_id, ProductView(None, sku, ean13(body), ar, en, cat_id, price, cost,
                                                            unit, Decimal(reorder)))
        catalogue_uc.adjust_stock(AdjustStockInput(admin_id, p.id, "RECEIPT", Decimal(100), "demo opening stock"))
