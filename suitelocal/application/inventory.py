from suitelocal.domain.auth import Session
from suitelocal.domain.models import Product
from suitelocal.domain.policies import require_owner
from suitelocal.infrastructure.repositories import ProductRepository


class InventoryService:
    def __init__(self, products: ProductRepository) -> None:
        self.products = products

    def create_product(
        self,
        session: Session,
        code: str,
        name: str,
        price_cents: int,
        stock: int,
    ) -> Product:
        require_owner(session)
        return self.products.add(code, name, price_cents, stock)

    def update_product(
        self,
        session: Session,
        product_id: int,
        code: str,
        name: str,
        price_cents: int,
        stock: int,
    ) -> Product:
        require_owner(session)
        return self.products.update(product_id, code, name, price_cents, stock)

    def deactivate_product(self, session: Session, product_id: int) -> None:
        require_owner(session)
        self.products.deactivate(product_id)
