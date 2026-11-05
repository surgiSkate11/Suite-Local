import re
from collections.abc import Iterable
from dataclasses import dataclass

from suitelocal.domain.money import DECIMAL_SEPARATORS

# Tax regimes an Ecuadorian business can be in, keyed by stored code.
TAX_REGIMES = {
    "sin_registro": "Sin registro en el SRI",
    "rimpe_popular": "RIMPE - Negocio popular",
    "rimpe_emprendedor": "RIMPE - Emprendedor",
    "general": "Régimen general",
}
DEFAULT_TAX_REGIME = "sin_registro"
_INVOICING_REGIMES = frozenset({"rimpe_emprendedor", "general"})

BUSINESS_TYPES = {
    "tienda": "Tienda",
    "minimarket": "Minimarket",
    "cafeteria": "Cafetería",
    "restaurante": "Restaurante",
    "ferreteria": "Ferretería",
    "otro": "Otro",
}
DEFAULT_BUSINESS_TYPE = "otro"

MODULES = frozenset({"mesas", "venta_por_peso", "codigo_barras", "categorias"})

ADDRESS_MAX_LENGTH = 200
PHONE_MAX_LENGTH = 30
RECEIPT_FOOTER_MAX_LENGTH = 300

_RUC_PATTERN = re.compile(r"[0-9]{13}")


@dataclass(frozen=True, slots=True)
class BusinessSettings:
    business_id: int
    name: str
    currency_symbol: str
    low_stock_threshold: int
    enabled_payment_methods: tuple[str, ...]
    # Default IVA rate offered for NEW products; every product carries its own rate.
    tax_rate_basis_points: int = 1500
    ruc: str = ""
    tax_regime: str = DEFAULT_TAX_REGIME
    business_type: str = DEFAULT_BUSINESS_TYPE
    enabled_modules: frozenset[str] = frozenset()
    decimal_separator: str = ","
    address: str = ""
    phone: str = ""
    receipt_footer: str = ""

    @property
    def tax_rate_percent(self) -> float:
        return self.tax_rate_basis_points / 100


@dataclass(frozen=True, slots=True)
class ProfileTemplate:
    modules: frozenset[str]
    categories: tuple[str, ...]


_RETAIL_TEMPLATE = ProfileTemplate(
    frozenset({"codigo_barras", "categorias"}),
    ("Abarrotes", "Bebidas", "Lácteos", "Limpieza", "Snacks"),
)
_FOOD_SERVICE_TEMPLATE = ProfileTemplate(
    frozenset({"mesas", "categorias"}),
    ("Café", "Bebidas", "Desayunos", "Postres"),
)
_TEMPLATES = {
    "tienda": _RETAIL_TEMPLATE,
    "minimarket": _RETAIL_TEMPLATE,
    "cafeteria": _FOOD_SERVICE_TEMPLATE,
    "restaurante": _FOOD_SERVICE_TEMPLATE,
    "ferreteria": ProfileTemplate(
        frozenset({"codigo_barras", "categorias", "venta_por_peso"}),
        ("Herramientas", "Eléctrico", "Plomería", "Pinturas", "Tornillería", "Materiales"),
    ),
    "otro": ProfileTemplate(frozenset({"categorias"}), ()),
}


def profile_template(business_type: str) -> ProfileTemplate:
    """Default modules and suggested categories for a business type (pure; applies nothing)."""
    return _TEMPLATES[validate_business_type(business_type)]


def validate_tax_regime(tax_regime: str) -> str:
    if tax_regime not in TAX_REGIMES:
        raise ValueError("El régimen tributario no es válido.")
    return tax_regime


def requires_ruc(tax_regime: str) -> bool:
    """Regimes that issue electronic invoices must identify themselves with a RUC."""
    return issues_electronic_invoices(tax_regime)


def issues_electronic_invoices(tax_regime: str) -> bool:
    """True for the regimes that must issue SRI electronic invoices."""
    return validate_tax_regime(tax_regime) in _INVOICING_REGIMES


def validate_business_type(business_type: str) -> str:
    if business_type not in BUSINESS_TYPES:
        raise ValueError("El tipo de negocio no es válido.")
    return business_type


def normalize_ruc(ruc: str) -> str:
    """Trim a RUC and check its shape; an empty RUC means "not set yet"."""
    ruc = ruc.strip()
    if not ruc:
        return ""
    # The modulo-10/11 check digit is deliberately not verified: the SRI rules for it have
    # exceptions (public and private companies, natural persons), and a wrong check would
    # reject real RUCs. Only the shape is validated here.
    if not _RUC_PATTERN.fullmatch(ruc):
        raise ValueError("El RUC debe tener exactamente 13 dígitos.")
    if ruc.endswith("000"):
        raise ValueError("El RUC no puede terminar en 000.")
    return ruc


def validate_ruc_for_regime(ruc: str, tax_regime: str) -> None:
    if not ruc and requires_ruc(tax_regime):
        raise ValueError("El RUC es obligatorio para este régimen tributario.")


def parse_modules(modules: Iterable[str] | str) -> frozenset[str]:
    """Accept stored comma-separated text or any iterable of module names."""
    names = modules.split(",") if isinstance(modules, str) else modules
    parsed = frozenset(name.strip() for name in names if name.strip())
    for name in sorted(parsed - MODULES):
        raise ValueError(f"El módulo «{name}» no existe.")
    return parsed


def format_modules(modules: Iterable[str]) -> str:
    return ",".join(sorted(parse_modules(modules)))


def validate_decimal_separator(decimal_separator: str) -> str:
    if decimal_separator not in DECIMAL_SEPARATORS:
        raise ValueError("El separador decimal debe ser «,» o «.».")
    return decimal_separator


def normalize_text(value: str, label: str, max_length: int) -> str:
    value = value.strip()
    if len(value) > max_length:
        raise ValueError(f"{label} no puede superar {max_length} caracteres.")
    return value
