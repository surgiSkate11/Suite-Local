import sqlite3
from collections.abc import Sequence

from suitelocal.domain.auth import Session
from suitelocal.domain.business import charges_iva
from suitelocal.domain.models import Payment, Sale, SaleItem
from suitelocal.domain.policies import require_owner
from suitelocal.domain.tables import ComandaLine, OpenOrder, Table, TableError, TableStatus
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import SaleRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.infrastructure.tables_repository import TablesRepository

_ORDER_CHANGED = "La cuenta cambió mientras se cobraba. Revisá la cuenta y volvé a cobrar."


def _billable_lines(items: Sequence[SaleItem]) -> list[tuple[int, int, int, int]]:
    """What a charge bills per product: quantity, unit price and IVA rate (names do not count)."""
    return sorted(
        (item.product_id, item.quantity, item.unit_price_cents, item.tax_rate_basis_points)
        for item in items
    )


class TablesService:
    """Open accounts per table: only the owner sets tables up, any user operates the orders."""

    def __init__(self, database: Database) -> None:
        self.tables = TablesRepository(database)
        self.sales = SaleRepository(database)
        self.settings = BusinessSettingsRepository(database)

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

    def sale_for(self, session: Session, order: OpenOrder, payments: Sequence[Payment]) -> Sale:
        """The sale an order becomes: the business regime decides whether its lines carry IVA."""
        regime = self.settings.get(session.user.business_id).tax_regime
        return Sale(
            order.sale_items(charges_iva(regime)),
            sum(payment.amount_cents for payment in payments),
            tuple(payments),
        )

    def charge(
        self,
        session: Session,
        order_id: int,
        payments: Sequence[Payment],
        customer_id: int | None = None,
    ) -> int:
        """Charge the order through the regular sale path and return the sale id.

        The sale (totals, IVA, payment and stock rules) is the existing one. The order is closed
        inside the sale's own transaction, so a failure at any step leaves the sale unregistered
        and the order open, and an order that was already charged cannot be charged again.
        ``customer_id`` links the sale to a customer of the business, in that same transaction.
        """
        business_id = session.user.business_id
        order = self.tables.get_order(business_id, order_id)
        sale = self.sale_for(session, order, payments)
        charged = _billable_lines(order.sale_items())

        def close_order(connection: sqlite3.Connection, sale_id: int) -> None:
            self.tables.close_in(connection, business_id, order_id, sale_id)
            # The order was read before this transaction began; if anyone changed what is being
            # billed since, the sale would not match the account, so the whole sale rolls back.
            current = self.tables.read_order_in(connection, order_id)
            if _billable_lines(current.sale_items()) != charged:
                raise TableError(_ORDER_CHANGED)

        return self.sales.register(
            sale,
            on_registered=close_order,
            business_id=business_id,
            user_id=session.user.id,
            customer_id=customer_id,
        )
