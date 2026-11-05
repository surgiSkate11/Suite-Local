from suitelocal.domain.auth import Session
from suitelocal.domain.policies import require_owner
from suitelocal.infrastructure.repositories import Category, CategoryRepository


class CategoryService:
    """Owner-managed product categories, scoped to the session's business."""

    def __init__(self, categories: CategoryRepository) -> None:
        self.categories = categories

    def list(self, session: Session, include_inactive: bool = False) -> list[Category]:
        # Any user may read: the cashier filters the catalog by category.
        return self.categories.list(session.user.business_id, include_inactive)

    def create(self, session: Session, name: str) -> Category:
        require_owner(session)
        return self.categories.add(session.user.business_id, name)

    def rename(self, session: Session, category_id: int, name: str) -> Category:
        require_owner(session)
        return self.categories.rename(session.user.business_id, category_id, name)

    def set_active(self, session: Session, category_id: int, active: bool) -> None:
        require_owner(session)
        self.categories.set_active(session.user.business_id, category_id, active)

    def delete(self, session: Session, category_id: int) -> None:
        require_owner(session)
        self.categories.delete(session.user.business_id, category_id)
