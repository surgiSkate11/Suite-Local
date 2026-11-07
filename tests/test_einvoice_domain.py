import re
from datetime import date
from pathlib import Path

import pytest

from suitelocal.domain.einvoice import (
    BUYER_ID_TYPES,
    FINAL_CONSUMER_ID,
    Buyer,
    access_key,
    iva_percentage_code,
    modulo11_check_digit,
    payment_code,
    validate_buyer,
)

FIXTURES = Path(__file__).parent / "fixtures" / "sri"
# The SRI formas de pago catalog (Ficha Técnica, tabla 24) as it appears in the reference code.
PAYMENT_CATALOG = {"01", "15", "16", "17", "18", "19", "20", "21"}
KEY_ARGS = ("01", "1234567890001", "1", "001", "001", "000000005", "12345678")


def reference_check_digit(digits: str) -> int:
    """Independent spelling of the rule: weights 2..7 from the right, 11 -> 0 and 10 -> 1."""
    total = sum(int(digit) * (2 + position % 6) for position, digit in enumerate(reversed(digits)))
    result = 11 - total % 11
    return {11: 0, 10: 1}.get(result, result)


# -- access key ----------------------------------------------------------------------------


def test_access_key_matches_the_example_key_of_the_sri_technical_sheet():
    # Example from the SRI Ficha Técnica, written down from memory (not re-checked offline):
    # 21/10/2011, RUC 1792146739001, environment 1, series 002001, sequential 1.
    key = access_key(
        date(2011, 10, 21), "01", "1792146739001", "1", "002", "001", "000000001", "12345678"
    )

    assert key == "2110201101179214673900110020010000000011234567813"
    assert len(key) == 49


def test_access_key_rebuilds_the_first_48_digits_of_the_clave_in_the_reference_original_xml():
    xml = (FIXTURES / "original.xml").read_text(encoding="utf-8")
    expected = re.search(r"<claveAcceso>(\d{49})</claveAcceso>", xml)
    assert expected is not None
    clave = expected.group(1)

    rebuilt = access_key(
        date(int(clave[4:8]), int(clave[2:4]), int(clave[0:2])),
        clave[8:10],
        clave[10:23],
        clave[23],
        clave[24:27],
        clave[27:30],
        clave[30:39],
        clave[39:47],
        clave[47],
    )

    assert rebuilt[:-1] == clave[:-1]
    # The sample key was typed by hand in the signer library: its last digit ("6") does not
    # satisfy módulo 11, and the signer never validates it. Ours follows the SRI rule.
    assert clave[-1] == "6"
    assert rebuilt[-1] == str(reference_check_digit(clave[:-1])) == "2"


def test_access_key_layout_is_date_type_ruc_environment_series_sequential_code_emission():
    key = access_key(
        date(2026, 3, 5), "01", "1790012345001", "2", "002", "003", "000000042", "00000007"
    )

    assert (
        key[:-1]
        == "05032026" + "01" + "1790012345001" + "2" + "002003" + "000000042" + "00000007" + "1"
    )


def test_check_digit_follows_weights_2_to_7_from_the_right():
    assert modulo11_check_digit("1") == "9"  # 1*2 = 2 -> 11 - 2
    assert modulo11_check_digit("11") == "6"  # 1*2 + 1*3 = 5 -> 11 - 5
    # Eight digits: the weights cycle 2..7 and start again at 2 for the eighth digit from the right.
    assert modulo11_check_digit("12345678") == str(reference_check_digit("12345678"))


def test_check_digit_special_cases_eleven_becomes_zero_and_ten_becomes_one():
    assert modulo11_check_digit("0") == "0"  # sum 0 -> 11 - 0 = 11 -> 0
    assert modulo11_check_digit("6") == "1"  # 6*2 = 12 -> 12 % 11 = 1 -> 10 -> 1


def test_access_key_applies_the_special_cases_on_a_full_key():
    seen: dict[int, str] = {}
    for number in range(200):
        code = f"{number:08d}"
        base = "05032026" + "01" + "1790012345001" + "1" + "001001" + "000000001" + code + "1"
        expected = reference_check_digit(base)
        if expected in (0, 1) and expected not in seen:
            seen[expected] = code
        if len(seen) == 2:
            break
    assert len(seen) == 2

    for digit, code in seen.items():
        key = access_key(
            date(2026, 3, 5), "01", "1790012345001", "1", "001", "001", "000000001", code
        )
        assert key[-1] == str(digit)


@pytest.mark.parametrize(
    ("index", "bad_value", "message"),
    [
        (0, "1", "El tipo de comprobante debe tener exactamente 2 dígitos."),
        (1, "123456789001", "El RUC debe tener exactamente 13 dígitos."),
        (1, "12345678900AB", "El RUC debe tener exactamente 13 dígitos."),
        (3, "01", "El establecimiento debe tener exactamente 3 dígitos."),
        (4, "0001", "El punto de emisión debe tener exactamente 3 dígitos."),
        (5, "5", "El secuencial debe tener exactamente 9 dígitos."),
        (6, "1234567", "El código numérico debe tener exactamente 8 dígitos."),
    ],
)
def test_access_key_rejects_wrong_field_lengths_with_a_spanish_error(index, bad_value, message):
    args = list(KEY_ARGS)
    args[index] = bad_value

    with pytest.raises(ValueError) as error:
        access_key(date(2024, 4, 18), *args)

    assert str(error.value) == message


@pytest.mark.parametrize("environment", ["", "3", "0", "12"])
def test_access_key_environment_must_be_1_or_2(environment):
    args = list(KEY_ARGS)
    args[2] = environment

    with pytest.raises(ValueError) as error:
        access_key(date(2024, 4, 18), *args)

    assert str(error.value) == "El ambiente debe ser 1 (pruebas) o 2 (producción)."


@pytest.mark.parametrize("emission_type", ["", "3", "11"])
def test_access_key_emission_type_must_be_1_or_2(emission_type):
    with pytest.raises(ValueError) as error:
        access_key(date(2024, 4, 18), *KEY_ARGS, emission_type=emission_type)

    assert str(error.value) == "El tipo de emisión debe ser 1 o 2."


# -- IVA and payment mappings --------------------------------------------------------------


@pytest.mark.parametrize(("basis_points", "code"), [(1500, "4"), (500, "5"), (0, "0")])
def test_iva_basis_points_map_to_the_sri_codigo_porcentaje(basis_points, code):
    assert iva_percentage_code(basis_points) == code


@pytest.mark.parametrize("basis_points", [1200, 1400, 100, -500])
def test_iva_mapping_rejects_rates_we_do_not_issue(basis_points):
    with pytest.raises(ValueError) as error:
        iva_percentage_code(basis_points)

    assert str(error.value) == "La tarifa de IVA debe ser 15 %, 5 % o 0 %."


@pytest.mark.parametrize(("method", "code"), [("cash", "01"), ("transfer", "20"), ("card", "19")])
def test_payment_methods_map_to_codes_of_the_sri_catalog(method, code):
    assert payment_code(method) == code
    assert code in PAYMENT_CATALOG


def test_payment_mapping_rejects_unknown_methods():
    with pytest.raises(ValueError) as error:
        payment_code("cheque")

    assert str(error.value) == "La forma de pago no es válida."


# -- buyer ---------------------------------------------------------------------------------


def test_buyer_id_types_follow_the_sri_table():
    assert set(BUYER_ID_TYPES) == {"04", "05", "06", "07", "08"}


def test_final_consumer_buyer_uses_the_reserved_identification_and_name():
    buyer = Buyer.final_consumer()

    assert (buyer.id_type, buyer.identification, buyer.name) == (
        "07",
        FINAL_CONSUMER_ID,
        "CONSUMIDOR FINAL",
    )
    assert FINAL_CONSUMER_ID == "9999999999999"
    validate_buyer(buyer, 5000)


def test_final_consumer_is_allowed_up_to_exactly_usd_50_and_rejected_above():
    validate_buyer(Buyer.final_consumer(), 5000)

    with pytest.raises(ValueError) as error:
        validate_buyer(Buyer.final_consumer(), 5001)

    assert str(error.value) == "Una factura a consumidor final no puede superar USD 50."


def test_final_consumer_requires_the_reserved_identification():
    buyer = Buyer("07", "1234567890123", "CONSUMIDOR FINAL")

    with pytest.raises(ValueError) as error:
        validate_buyer(buyer, 100)

    assert str(error.value) == "El consumidor final se identifica solo con 9999999999999."


def test_the_final_consumer_number_cannot_identify_a_named_buyer():
    with pytest.raises(ValueError) as error:
        validate_buyer(Buyer("05", "9999999999999", "Ana"), 100)

    assert str(error.value) == "El número 9999999999999 es solo para consumidor final."


@pytest.mark.parametrize(
    "buyer",
    [
        Buyer("05", "1712345678", "Ana Pérez"),
        Buyer("04", "1790012345001", "Empresa SA"),
        Buyer("06", "AB123456", "John Smith"),
        Buyer("08", "X-998877", "Pierre Dupont"),
    ],
)
def test_valid_buyers_pass_even_above_the_final_consumer_limit(buyer):
    validate_buyer(buyer, 1_000_000)


@pytest.mark.parametrize(
    ("buyer", "message"),
    [
        (Buyer("05", "171234567", "Ana"), "La cédula debe tener exactamente 10 dígitos."),
        (Buyer("05", "17123456AB", "Ana"), "La cédula debe tener exactamente 10 dígitos."),
        (Buyer("04", "179001234500", "Empresa"), "El RUC del comprador debe tener 13 dígitos."),
        (Buyer("04", "1790012345000", "Empresa"), "El RUC del comprador no puede terminar en 000."),
        (Buyer("06", "", "John"), "La identificación del comprador es obligatoria."),
        (
            Buyer("06", "A" * 21, "John"),
            "La identificación del comprador no puede superar 20 caracteres.",
        ),
        (Buyer("09", "123", "Ana"), "El tipo de identificación del comprador no es válido."),
        (Buyer("05", "1712345678", "  "), "El nombre del comprador es obligatorio."),
    ],
)
def test_invalid_buyers_are_rejected_with_a_spanish_error(buyer, message):
    with pytest.raises(ValueError) as error:
        validate_buyer(buyer, 100)

    assert str(error.value) == message
