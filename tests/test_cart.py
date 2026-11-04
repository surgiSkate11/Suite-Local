import pytest

from suitelocal.application.cart import Cart
from suitelocal.domain.models import Product, SaleError


def test_cart_accumulates_items_and_creates_sale():
    cart = Cart()
    cart.add(Product(1, "A-1", "Arroz", 250, 5))
    cart.add(Product(1, "A-1", "Arroz", 250, 5))

    sale = cart.to_sale(600)

    assert cart.total_cents == 500
    assert sale.items[0].quantity == 2
    assert sale.change_cents == 100


def test_cart_does_not_exceed_stock():
    cart = Cart()
    product = Product(1, "A-1", "Arroz", 250, 1)
    cart.add(product)

    with pytest.raises(ValueError, match="Stock insuficiente"):
        cart.add(product)


def test_empty_cart_cannot_be_confirmed():
    with pytest.raises(SaleError, match="al menos un producto"):
        Cart().to_sale(0)


def test_cart_rejects_zero_payment():
    cart = Cart()
    cart.add(Product(1, "A-1", "Arroz", 250, 5))

    with pytest.raises(SaleError, match="mayor que cero"):
        cart.to_sale(0)


def test_cart_calculates_tax_in_cents_with_half_up_rounding():
    cart = Cart(tax_rate_basis_points=1900)
    cart.add(Product(1, "A-1", "Arroz", 101, 5))

    sale = cart.to_sale(121)

    assert sale.subtotal_cents == 101
    assert sale.tax_cents == 19
    assert sale.total_cents == 120
    assert sale.change_cents == 1


def test_cart_can_edit_quantity_without_exceeding_stock():
    cart = Cart()
    product = Product(1, "A-1", "Arroz", 250, 5)
    cart.add(product)
    cart.set_quantity(product.id, 4)

    assert cart.lines[0].quantity == 4

    with pytest.raises(ValueError, match="Stock insuficiente"):
        cart.set_quantity(product.id, 6)
