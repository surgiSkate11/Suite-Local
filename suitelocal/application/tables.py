from collections.abc import Sequence

from suitelocal.domain.auth import Session
from suitelocal.domain.models import Payment, Sale
from suitelocal.domain.policies import require_owner
from suitelocal.domain.tables import ComandaLine, OpenOrder, Table, TableStatus
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import SaleRepository
from suitelocal.infrastructure.tables_repository import TablesRepository


class TablesService:
    """Open accounts per table: only the owner sets tables up, any user operates the orders."""

    def __init__(self, database: Database) -> None:
        self.tables = TablesRepository(database)
        self.sales = SaleRepository(database)

    def create_table(self, session: Session, name: str, zone: str | None = None) -> Table:
        require_owner(session)
        return self.tables.add_table(session.user.business_id, name, zone)

    def list_tables(self, session: Session) -> list[TableStatus]:
        business_id = session.user.business_id
        orders = self.tables.open_orders(business_id)
        return [
            TableStatus(table, orders.get(table.id))
            for table in self.tables.list_tables(business_id)
        ]

    def get_order(self, session: Session, table_id: int) -> OpenOrder | None:
        return self.tables.order_for_table(session.user.business_id, table_id)

    def open_order(self, session: Session, table_id: int) -> OpenOrder:
        return self.tables.open_order(session.user.business_id, table_id)

    def add_product(
        self, session: Session, order_id: int, product_id: int, quantity: int = 1
    ) -> OpenOrder:
        return self.tables.add_product(session.user.business_id, order_id, product_id, quantity)

    def set_quantity(
        self, session: Session, order_id: int, product_id: int, quantity: int
    ) -> OpenOrder:
        return self.tables.set_quantity(session.user.business_id, order_id, product_id, quantity)

    def remove_line(self, session: Session, order_id: int, product_id: int) -> OpenOrder:
        return self.tables.remove_line(session.user.business_id, order_id, product_id)

    def send_to_kitchen(self, session: Session, order_id: int) -> list[ComandaLine]:
        return self.tables.mark_sent(session.user.business_id, order_id)

    def transfer(self, session: Session, order_id: int, target_table_id: int) -> OpenOrder:
        return self.tables.transfer(session.user.business_id, order_id, target_table_id)

    def cancel(self, session: Session, order_id: int) -> None:
        self.tables.cancel(session.user.business_id, order_id)

    def charge(
        self,
        session: Session,
        order_id: int,
        payments: Sequence[Payment],
        tax_rate_basis_points: int = 0,
    ) -> int:
        """Charge the order through the regular sale path and return the sale id.

        The sale (totals, tax, payment and stock rules) is the existing one; the order is only
        closed after it is registered, so any failure leaves the order open and unchanged.
        """
        business_id = session.user.business_id
        order = self.tables.get_order(business_id, order_id)
        sale = Sale(
            order.sale_items(),
            sum(payment.amount_cents for payment in payments),
            tuple(payments),
            tax_rate_basis_points,
        )
        sale_id = self.sales.register(sale)
        self.tables.close(business_id, order_id, sale_id)
        return sale_id
