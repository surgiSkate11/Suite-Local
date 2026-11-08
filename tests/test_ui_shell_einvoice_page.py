# ruff: noqa: F811 - the imported fixtures are used by name as test arguments
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from test_ui_shell_einvoice import (  # noqa: F401 - fixtures are collected from this module
    DECIDED,
    env,
    make_shell,
    qapp,
    rsa_key,
    toasts,
)

from suitelocal.domain.einvoice import PENDING, Buyer
from suitelocal.infrastructure.sri.queue import EInvoiceRepository

LABEL = "Facturas electrónicas"


def entries(shell) -> list[tuple[str, str]]:
    """(group, label) of every rail entry, in order."""
    result: list[tuple[str, str]] = []
    group = ""
    for row in range(shell.navigation.count()):
        item = shell.navigation.item(row)
        if item.data(Qt.ItemDataRole.UserRole) == "section":
            group = item.text()
        else:
            result.append((group, item.text()))
    return result


def test_the_page_is_in_the_negocio_group_when_invoicing_is_enabled(env, make_shell):
    env.profile.update_einvoice(env.owner, enabled=True)
    shell = make_shell()

    assert ("Negocio", LABEL) in entries(shell)
    assert shell.einvoices_page is not None


def test_the_page_is_absent_while_invoicing_is_disabled(env, make_shell):
    shell = make_shell()

    assert LABEL not in [label for _group, label in entries(shell)]
    assert shell.einvoices_page is None


def test_selecting_the_entry_opens_the_page(env, make_shell):
    env.profile.update_einvoice(env.owner, enabled=True)
    shell = make_shell()
    row = next(
        row for row in range(shell.navigation.count()) if shell.navigation.item(row).text() == LABEL
    )

    shell.navigation.setCurrentRow(row)

    # Every page lives inside its own scroll area, so the stack shows the page's scroll wrapper.
    assert shell.pages.currentWidget() is shell.einvoices_page.parentWidget().parentWidget()


def test_the_comprobante_section_follows_the_invoicing_module(env, make_shell):
    off = make_shell()
    assert off.pos_widget.buyer_section.isHidden()

    env.profile.update_einvoice(env.owner, enabled=True)
    on = make_shell()

    assert not on.pos_widget.buyer_section.isHidden()
    assert on.pos_widget.invoicing_active is True


def test_process_now_runs_a_pass_and_the_page_refreshes_after_it(env, make_shell):
    env.profile.update_einvoice(env.owner, enabled=True)
    env.add_invoice("recibida")
    env.gateway.answer = DECIDED
    shell = make_shell()
    page = shell.einvoices_page
    assert page is not None
    status = page.table.cellWidget(0, 4)
    assert status is not None and status.text() == "•  Recibida"

    page.process_button.click()

    assert env.gateway.authorized != []
    status = page.table.cellWidget(0, 4)
    assert status is not None and status.text() == "•  Autorizada"


def test_a_failed_reception_pass_still_refreshes_the_page(env, make_shell):
    env.profile.update_einvoice(env.owner, enabled=True)
    env.add_invoice("recibida")
    shell = make_shell()
    page = shell.einvoices_page
    assert page is not None
    env.add_invoice("devuelta")

    shell.einvoice_runner.tick()

    assert page.table.rowCount() == 2


def test_page_notifications_become_toasts(env, make_shell):
    env.profile.update_einvoice(env.owner, enabled=True)
    shell = make_shell()
    assert shell.einvoices_page is not None

    shell.einvoices_page.notification.emit("Factura reemitida.", "success")

    assert [toast.message for toast in toasts(shell)] == ["Factura reemitida."]


def test_enabling_invoicing_in_settings_turns_the_section_on_and_tells_about_the_page(
    env, make_shell
):
    shell = make_shell()
    assert shell.pos_widget.buyer_section.isHidden()

    env.profile.update_einvoice(env.owner, enabled=True)
    shell._on_business_changed()

    assert not shell.pos_widget.buyer_section.isHidden()
    assert shell.einvoices_page is None
    assert [toast.message for toast in toasts(shell)] == [
        "La página de Facturas electrónicas aparece la próxima vez que inicies sesión."
    ]


def test_an_issued_invoice_refreshes_the_status_bar_count(env, make_shell):
    env.profile.update_einvoice(env.owner, enabled=True)
    shell = make_shell()
    assert shell.status_sri_item.isHidden()
    pos = shell.pos_widget
    pos.products.add("Z-1", "Pan", 100, 10, tax_rate_basis_points=0)
    pos.refresh_products()
    pos.search_input.setText("Z-1")
    pos.add_selected_product()
    pos.received_edit.setText("1.00")
    pos.print_switch.setChecked(False)

    pos.confirm_sale()

    assert pos.last_sale_id is not None
    invoice = EInvoiceRepository(env.database).get_for_sale(
        env.owner.user.business_id, pos.last_sale_id
    )
    assert invoice is not None and invoice.status == PENDING
    assert invoice.buyer == Buyer.final_consumer()
    assert not shell.status_sri_item.isHidden()
    assert shell.status_sri.text() == "SRI: 1 pendiente"
