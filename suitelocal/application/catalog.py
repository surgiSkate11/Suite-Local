from suitelocal.domain.auth import Session
from suitelocal.domain.models import Product
from suitelocal.infrastructure.repositories import ProductRepository


class CatalogService:
    """Read-only product lookup for screens that sell: any signed-in user may search."""

    def __init__(self, products: ProductRepository) -> None:
        self.products = products

    def search(self, session: Session, text: str) -> list[Product]:
        """Active products whose code or name contains ``text``; blank text lists them all."""
        return self.products.find_active(text)
