from suitelocal.domain.auth import Session
from suitelocal.domain.models import KEEP, Keep, Product
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
        category_id: int | None = None,
        cost_cents: int | None = None,
        tax_rate_basis_points: int | None = None,
    ) -> Product:
        require_owner(session)
        return self.products.add(
            code,
            name,
            price_cents,
            stock,
            category_id,
            cost_cents,
            tax_rate_basis_points,
            business_id=session.user.business_id,
        )

    def update_product(
        self,
        session: Session,
        product_id: int,
        code: str,
        name: str,
        price_cents: int,
        stock: int,
        tax_rate_basis_points: int | Keep = KEEP,
        category_id: int | None | Keep = KEEP,
        cost_cents: int | None | Keep = KEEP,
    ) -> Product:
        """Update a product; the rate, category and cost stay as they are unless given."""
        require_owner(session)
        return self.products.update(
            product_id,
            code,
            name,
            price_cents,
            stock,
            category_id,
            cost_cents,
            tax_rate_basis_points,
            business_id=session.user.business_id,
        )

    def deactivate_product(self, session: Session, product_id: int) -> None:
        require_owner(session)
        self.products.deactivate(product_id)
