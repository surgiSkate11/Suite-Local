"""Customers of a business: who they are, how they are identified and what may be stored."""

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime

from suitelocal.domain.einvoice import Buyer, validate_buyer

CUSTOMER_ID_TYPES = ("cedula", "ruc", "pasaporte")
ID_TYPE_LABELS = {"cedula": "Cédula", "ruc": "RUC", "pasaporte": "Pasaporte"}
# SRI "tipoIdentificacionComprador" of each customer identification type.
_BUYER_ID_TYPES = {"cedula": "05", "ruc": "04", "pasaporte": "06"}

NAME_MAX_LENGTH = 100
PHONE_MAX_LENGTH = 20
ADDRESS_MAX_LENGTH = 200
EMAIL_MAX_LENGTH = 100

_PASSPORT = re.compile(r"[A-Za-z0-9]{3,20}")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


@dataclass(frozen=True, slots=True)
class CustomerData:
    """What the cashier types to register or edit a customer."""

    id_type: str
    id_number: str
    full_name: str
    phone: str = ""
    address: str = ""
    email: str = ""
    accepts_offers: bool = False


@dataclass(frozen=True, slots=True)
class Customer:
    id: int
    business_id: int
    id_type: str
    id_number: str
    full_name: str
    phone: str
    address: str
    email: str
    accepts_offers: bool
    active: bool
    created_at: str

    def as_buyer(self) -> Buyer:
        """The invoice buyer of this customer."""
        return Buyer(_BUYER_ID_TYPES[self.id_type], self.id_number, self.full_name, self.address)


@dataclass(frozen=True, slots=True)
class Purchase:
    sale_id: int
    created_at: datetime
    total_cents: int


@dataclass(frozen=True, slots=True)
class CustomerHistory:
    """The latest purchases of a customer and what they bought over all time."""

    purchases: tuple[Purchase, ...]
    purchase_count: int
    total_cents: int


def buyer_id_type(id_type: str) -> str:
    """SRI buyer type code of a customer identification type: cédula 05, RUC 04, pasaporte 06."""
    return _BUYER_ID_TYPES[id_type]


def customer_id_type(buyer_type: str) -> str | None:
    """The customer identification type of an SRI buyer code, or None when it has no equivalent."""
    for id_type, code in _BUYER_ID_TYPES.items():
        if code == buyer_type:
            return id_type
    return None


def fold_text(text: str) -> str:
    """Lowercase without accents, so "José" and "jose" compare equal."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def validate_customer(data: CustomerData) -> CustomerData:
    """Trim the fields and check them; return the cleaned data or raise a Spanish ValueError."""
    data = replace(
        data,
        id_number=data.id_number.strip(),
        full_name=" ".join(data.full_name.split()),
        phone=data.phone.strip(),
        address=data.address.strip(),
        email=data.email.strip().lower(),
    )
    if data.id_type not in CUSTOMER_ID_TYPES:
        raise ValueError("El tipo de identificación no es válido.")
    if not data.full_name:
        raise ValueError("El nombre del cliente es obligatorio.")
    if data.id_type == "pasaporte":
        if not _PASSPORT.fullmatch(data.id_number):
            raise ValueError("El pasaporte debe tener entre 3 y 20 letras o dígitos.")
    else:
        # Same rules as the invoice buyer, so a saved customer can always be invoiced.
        validate_buyer(Buyer(_BUYER_ID_TYPES[data.id_type], data.id_number, data.full_name), 0)
    if len(data.full_name) > NAME_MAX_LENGTH:
        raise ValueError(f"El nombre no puede superar {NAME_MAX_LENGTH} caracteres.")
    if len(data.phone) > PHONE_MAX_LENGTH:
        raise ValueError(f"El teléfono no puede superar {PHONE_MAX_LENGTH} caracteres.")
    if len(data.address) > ADDRESS_MAX_LENGTH:
        raise ValueError(f"La dirección no puede superar {ADDRESS_MAX_LENGTH} caracteres.")
    if data.email and (len(data.email) > EMAIL_MAX_LENGTH or not _EMAIL.fullmatch(data.email)):
        raise ValueError("El correo no es válido.")
    if data.accepts_offers and not data.email:
        raise ValueError("Para recibir ofertas necesitás registrar un correo.")
    return data
