from collections.abc import Callable, Iterable
from datetime import datetime
from decimal import Decimal

from suitelocal.domain.auth import Session
from suitelocal.domain.business import BusinessSettings, profile_template
from suitelocal.domain.policies import require_owner
from suitelocal.infrastructure.repositories import CategoryRepository
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.infrastructure.sri.certificate_store import CertificateInfo, CertificateStore

_NO_CERTIFICATE_STORE = "El almacén de certificados no está configurado."


class BusinessProfileService:
    """Owner-only writes of the business settings and the Ecuador business profile."""

    def __init__(
        self,
        settings: BusinessSettingsRepository,
        categories: CategoryRepository,
        certificates: Callable[[int], CertificateStore] | None = None,
    ) -> None:
        self.settings = settings
        self.categories = categories
        self._certificates = certificates

    def certificates(self, business_id: int) -> CertificateStore:
        """The protected certificate store of a business."""
        if self._certificates is None:
            raise ValueError(_NO_CERTIFICATE_STORE)
        return self._certificates(business_id)

    def _has_certificate(self, business_id: int) -> bool:
        return self._certificates is not None and self._certificates(business_id).exists()

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
        receipt_paper_mm: int | None = None,
        printer_name: str | None = None,
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
            receipt_paper_mm=receipt_paper_mm,
            printer_name=printer_name,
        )

    def update_einvoice(
        self,
        session: Session,
        *,
        enabled: bool | None = None,
        sri_environment: str | None = None,
        establishment: str | None = None,
        emission_point: str | None = None,
        obligado_contabilidad: bool | None = None,
        trade_name: str | None = None,
    ) -> BusinessSettings:
        """Change only the given electronic-invoicing fields; turning it on has prerequisites."""
        require_owner(session)
        business_id = session.user.business_id
        return self.settings.update_einvoice(
            business_id,
            enabled=enabled,
            sri_environment=sri_environment,
            establishment=establishment,
            emission_point=emission_point,
            obligado_contabilidad=obligado_contabilidad,
            trade_name=trade_name,
            has_certificate=self._has_certificate(business_id),
        )

    def save_certificate(
        self, session: Session, p12_bytes: bytes, password: str, *, now: datetime | None = None
    ) -> CertificateInfo:
        """Check and store the signing certificate; SigningError (nothing stored) if it is bad."""
        require_owner(session)
        store = self.certificates(session.user.business_id)
        store.save(p12_bytes, password, now=now)
        return store.info()

    def certificate_info(self, session: Session) -> CertificateInfo | None:
        """What the owner may see of the stored certificate, or None when there is none."""
        require_owner(session)
        if not self._has_certificate(session.user.business_id):
            return None
        return self.certificates(session.user.business_id).info()

    def remove_certificate(self, session: Session) -> None:
        require_owner(session)
        business_id = session.user.business_id
        if self.settings.get(business_id).einvoice_enabled:
            raise ValueError(
                "Primero se debe desactivar la factura electrónica para quitar el certificado."
            )
        self.certificates(business_id).clear()

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
