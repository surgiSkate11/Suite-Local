from collections.abc import Iterable
from decimal import Decimal

from suitelocal.domain.auth import Session
from suitelocal.domain.business import BusinessSettings, profile_template
from suitelocal.domain.policies import require_owner
from suitelocal.infrastructure.repositories import CategoryRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository


class BusinessProfileService:
    """Owner-only writes of the business settings and the Ecuador business profile."""

    def __init__(
        self, settings: BusinessSettingsRepository, categories: CategoryRepository
    ) -> None:
        self.settings = settings
        self.categories = categories

    def get(self, session: Session) -> BusinessSettings:
        return self.settings.get(session.user.business_id)

    def update_settings(
        self,
        session: Session,
        name: str,
        currency_symbol: str,
        low_stock_threshold: int,
        enabled_payment_methods: tuple[str, ...],
        tax_rate_percent: str | Decimal | int | float | None = None,
    ) -> BusinessSettings:
        require_owner(session)
        return self.settings.update(
            session.user.business_id,
            name,
            currency_symbol,
            low_stock_threshold,
            enabled_payment_methods,
            tax_rate_percent,
        )

    def update_profile(
        self,
        session: Session,
        *,
        ruc: str | None = None,
        tax_regime: str | None = None,
        business_type: str | None = None,
        enabled_modules: Iterable[str] | None = None,
        decimal_separator: str | None = None,
        address: str | None = None,
        phone: str | None = None,
        receipt_footer: str | None = None,
    ) -> BusinessSettings:
        """Change only the given profile fields; changing the type never applies its template."""
        require_owner(session)
        return self.settings.update_profile(
            session.user.business_id,
            ruc=ruc,
            tax_regime=tax_regime,
            business_type=business_type,
            enabled_modules=enabled_modules,
            decimal_separator=decimal_separator,
            address=address,
            phone=phone,
            receipt_footer=receipt_footer,
        )

    def apply_template(self, session: Session, business_type: str) -> BusinessSettings:
        """Explicitly adopt a business type: replace its modules and add the missing categories."""
        require_owner(session)
        template = profile_template(business_type)
        business_id = session.user.business_id
        # One transaction: a failure while adding categories also undoes the settings change.
        with self.settings.database.connect() as connection:
            self.settings.write_profile(
                connection,
                business_id,
                business_type=business_type,
                enabled_modules=template.modules,
            )
            self.categories.add_missing(business_id, template.categories, connection)
        return self.settings.get(business_id)
