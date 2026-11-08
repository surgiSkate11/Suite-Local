"""A business with electronic invoicing ready (certificate, RUC, regime), shared by UI tests."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import rsa
from test_certificate_store import FakeProtector
from test_xades import make_p12

from suitelocal.application.auth import AuthService
from suitelocal.application.business_profile import BusinessProfileService
from suitelocal.application.einvoice import EInvoiceService
from suitelocal.application.receipts import ReceiptService
from suitelocal.domain.auth import Session
from suitelocal.domain.models import Payment, Sale, SaleItem
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.repositories import (
    CategoryRepository,
    ProductRepository,
    SaleRepository,
)
from suitelocal.infrastructure.settings import BusinessSettingsRepository
from suitelocal.infrastructure.sri.certificate_store import CertificateStore

RUC = "1790012345001"
ECUADOR = timezone(timedelta(hours=-5))


@dataclass
class EInvoiceEnv:
    database: Database
    auth: AuthService
    owner: Session
    cashier: Session
    profile: BusinessProfileService
    service: EInvoiceService
    products: ProductRepository
    sales: SaleRepository
    receipts: ReceiptService
    settings: BusinessSettingsRepository
    certificates_root: Path
    sales_made: int = 0

    def certificates(self, business_id: int) -> CertificateStore:
        return CertificateStore.for_business(self.certificates_root, business_id, FakeProtector())

    def sell(self, price_cents: int = 115, rate: int = 1500, quantity: int = 1) -> int:
        """One line sold and paid in cash; returns the sale id."""
        self.sales_made += 1
        product = self.products.add(
            f"S-{self.sales_made}", "Arroz", price_cents, 50, tax_rate_basis_points=rate
        )
        total = price_cents * quantity
        return self.sales.register(
            Sale(
                (SaleItem(product.id, product.name, quantity, price_cents, rate),),
                total,
                (Payment("cash", total),),
            ),
            business_id=self.owner.user.business_id,
            user_id=self.owner.user.id,
        )


def build_env(tmp_path: Path, rsa_key: rsa.RSAPrivateKey, *, enabled: bool = True) -> EInvoiceEnv:
    database = Database(tmp_path / "einvoice.db")
    database.initialize()
    auth = AuthService(database)
    owner = Session(auth.setup_owner("Tienda Sol", "owner", "clave-segura", "clave-segura"))
    cashier = Session(auth.create_cashier(owner, "cajero", "clave-cajero", "clave-cajero"))
    root = tmp_path / "data"
    settings = BusinessSettingsRepository(database)
    profile = BusinessProfileService(
        settings,
        CategoryRepository(database),
        lambda business_id: CertificateStore.for_business(root, business_id, FakeProtector()),
    )
    profile.update_profile(
        owner, tax_regime="rimpe_emprendedor", ruc=RUC, address="Av. Amazonas 123"
    )
    now = datetime.now(UTC)
    p12 = make_p12(
        rsa_key, b"clave", not_before=now - timedelta(days=1), not_after=now + timedelta(days=365)
    )
    profile.save_certificate(owner, p12, "clave")
    if enabled:
        profile.update_einvoice(owner, enabled=True, trade_name="La Esquina")
    service = EInvoiceService(
        database, profile.certificates, timezone=ECUADOR, numeric_code=lambda: "12345678"
    )
    return EInvoiceEnv(
        database,
        auth,
        owner,
        cashier,
        profile,
        service,
        ProductRepository(database),
        SaleRepository(database),
        ReceiptService(database, ECUADOR),
        settings,
        root,
    )
