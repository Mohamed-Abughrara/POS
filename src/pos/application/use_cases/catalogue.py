"""UC-10 ManageCatalogue (products, categories, customers) and UC-11 AdjustStock."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from ...domain.entities import Category, Customer, MovementType, Product, StockMovement
from ...domain.errors import InvalidQuantity
from ...domain.money import Money
from ...domain.quantity import Unit
from ...domain.tax import TaxRate
from ..dto import (AdjustStockInput, CategoryView, CustomerView, ProductView, StockLevelView)
from ..errors import DuplicateEntity, NotFound, ProductNotFound
from ..permissions import Permission
from ..ports import UnitOfWork
from .common import UseCase


def _product_view(p: Product, on_hand: Optional[Decimal] = None) -> ProductView:
    return ProductView(p.id, p.sku, p.barcode, p.name_ar, p.name_en, p.category_id, p.price.amount,
                       p.cost.amount, p.unit.value, p.reorder_level, p.is_active, on_hand,
                       p.tax_rate.basis_points)


class CatalogueUseCases(UseCase):
    # ---- products ------------------------------------------------------------
    def search_products(self, actor_id: str, query: str = "", include_inactive: bool = True,
                        limit: int = 200) -> list[ProductView]:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.SELL)
            return [_product_view(p, uow.stock.on_hand(p.id))
                    for p in uow.products.search(query, limit, include_inactive)]

    def save_product(self, actor_id: str, view: ProductView) -> ProductView:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.CATALOGUE)
            existing = uow.products.get(view.id) if view.id else None
            product = Product(
                id=view.id or self._ids.new_id(), sku=view.sku.strip(), barcode=view.barcode,
                name_ar=view.name_ar.strip(), name_en=view.name_en.strip(),
                category_id=view.category_id, price=Money(view.price), cost=Money(view.cost),
                unit=Unit(view.unit), reorder_level=Decimal(view.reorder_level), is_active=view.is_active)
            other = uow.products.get_by_sku(product.sku)
            if other and other.id != product.id:
                raise DuplicateEntity(f"sku {product.sku}")
            if product.barcode:
                other = uow.products.get_by_barcode(product.barcode)
                if other and other.id != product.id:
                    raise DuplicateEntity(f"barcode {product.barcode}")
            uow.products.save(product)
            if existing is None:
                self._audit(uow, actor_id, "PRODUCT_CREATED", "product", product.id, sku=product.sku)
            elif existing.price != product.price:
                self._audit(uow, actor_id, "PRICE_CHANGE", "product", product.id,
                            old=existing.price.amount, new=product.price.amount)
            elif existing.is_active != product.is_active:
                self._audit(uow, actor_id, "PRODUCT_ACTIVE_CHANGED", "product", product.id,
                            active=product.is_active)
            uow.commit()
            saved = uow.products.get(product.id)
            return _product_view(saved, uow.stock.on_hand(product.id))

    def set_product_active(self, actor_id: str, product_id: str, active: bool) -> None:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.CATALOGUE)
            p = uow.products.get(product_id)
            if p is None:
                raise ProductNotFound(product_id)
            p.is_active = active
            uow.products.save(p)
            self._audit(uow, actor_id, "PRODUCT_ACTIVE_CHANGED", "product", p.id, active=active)
            uow.commit()

    # ---- categories ----------------------------------------------------------
    def list_categories(self, actor_id: str) -> list[CategoryView]:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.SELL)
            return [CategoryView(c.id, c.name_ar, c.name_en, c.tax_rate.basis_points, c.tax_rate.inclusive)
                    for c in uow.categories.list()]

    def save_category(self, actor_id: str, view: CategoryView) -> CategoryView:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.CATALOGUE)
            cat = Category(view.id or self._ids.new_id(), view.name_ar, view.name_en,
                           TaxRate(view.tax_bp, view.tax_inclusive))
            uow.categories.save(cat)
            self._audit(uow, actor_id, "CATEGORY_SAVED", "category", cat.id, tax_bp=view.tax_bp)
            uow.commit()
            return CategoryView(cat.id, cat.name_ar, cat.name_en, view.tax_bp, view.tax_inclusive)

    # ---- customers -----------------------------------------------------------
    def search_customers(self, actor_id: str, query: str = "") -> list[CustomerView]:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.SELL)
            return [CustomerView(c.id, c.name, c.phone, c.loyalty_id) for c in uow.customers.search(query)]

    def save_customer(self, actor_id: str, view: CustomerView) -> CustomerView:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.SELL)
            c = Customer(view.id or self._ids.new_id(), view.name.strip(),
                         (view.phone or "").strip() or None, (view.loyalty_id or "").strip() or None)
            if c.phone:
                clash = [x for x in uow.customers.search(c.phone) if x.phone == c.phone and x.id != c.id]
                if clash:
                    raise DuplicateEntity(f"phone {c.phone}")
            uow.customers.save(c)
            uow.commit()
            return CustomerView(c.id, c.name, c.phone, c.loyalty_id)

    # ---- stock (UC-11) -------------------------------------------------------
    def adjust_stock(self, inp: AdjustStockInput) -> StockLevelView:
        with self._uow_factory() as uow:
            self._user(uow, inp.actor_id, Permission.STOCK)
            product = uow.products.get(inp.product_id)
            if product is None:
                raise ProductNotFound(inp.product_id)
            mtype = MovementType(inp.type)
            if mtype not in (MovementType.RECEIPT, MovementType.ADJUSTMENT, MovementType.WASTE):
                raise InvalidQuantity("movement type not allowed here")
            delta = Decimal(inp.qty_delta)
            if delta == 0:
                raise InvalidQuantity("quantity must not be zero")
            if mtype == MovementType.RECEIPT:
                delta = abs(delta)
            elif mtype == MovementType.WASTE:
                delta = -abs(delta)
            if product.unit == Unit.PIECE and delta != delta.to_integral_value():
                raise InvalidQuantity("pieces must be whole")
            uow.stock.append(StockMovement(self._ids.new_id(), product.id, mtype, delta, None,
                                           inp.actor_id, self._clock.now(), inp.reason))
            self._audit(uow, inp.actor_id, "STOCK_" + mtype.value, "product", product.id,
                        delta=str(delta), reason=inp.reason)
            uow.commit()
            on_hand = uow.stock.on_hand(product.id)
            return StockLevelView(product.id, on_hand, on_hand <= product.reorder_level)

    def low_stock(self, actor_id: str) -> list[ProductView]:
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.STOCK)
            return [_product_view(p, qty) for p, qty in uow.stock.low_stock()]
