from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from suitelocal.infrastructure.backups import BackupError, create_backup, restore_backup
from suitelocal.infrastructure.database import Database
from suitelocal.infrastructure.settings import BusinessSettingsRepository


class SettingsWidget(QWidget):
    def __init__(
        self,
        settings: BusinessSettingsRepository,
        business_id: int,
        database: Database,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.business_id = business_id
        self.database = database
        current = settings.get(business_id)
        self.name = QLineEdit(current.name)
        self.currency = QLineEdit(current.currency_symbol)
        self.threshold = QSpinBox()
        self.threshold.setRange(0, 1_000_000)
        self.threshold.setValue(current.low_stock_threshold)
        self.tax_rate = QLineEdit(f"{current.tax_rate_percent:g}")
        self.tax_rate.setPlaceholderText("Ej. 19")
        self.transfer = QCheckBox("Transferencia")
        self.transfer.setChecked("transfer" in current.enabled_payment_methods)
        self.card = QCheckBox("Tarjeta con datáfono configurado")
        self.card.setChecked(False)
        self.card.setEnabled(False)
        self.card.setToolTip("Se habilitará al configurar un proveedor de datáfono.")
        self.card.setMinimumWidth(0)
        save = QPushButton("Guardar configuración")
        save.clicked.connect(self.save)
        self.message = QLabel()
        self.message.setObjectName("inlineMessage")
        form = QFormLayout()
        form.addRow("Nombre del negocio:", self.name)
        form.addRow("Símbolo monetario:", self.currency)
        form.addRow("Avisar stock bajo en:", self.threshold)
        form.addRow("IVA (%):", self.tax_rate)
        form.addRow(save)
        title = QLabel("Configuración")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Adapta SuiteLocal a la forma de trabajar de tu empresa.")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setMinimumWidth(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 30)
        layout.setSpacing(16)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        business_card = QFrame()
        business_card.setObjectName("contentCard")
        business_layout = QVBoxLayout(business_card)
        business_layout.setContentsMargins(20, 18, 20, 18)
        business_title = QLabel("Datos del negocio")
        business_title.setObjectName("sectionTitle")
        business_layout.addWidget(business_title)
        business_layout.addLayout(form)

        payments_card = QFrame()
        payments_card.setObjectName("contentCard")
        payments_layout = QVBoxLayout(payments_card)
        payments_layout.setContentsMargins(20, 18, 20, 18)
        payments_title = QLabel("Métodos de pago")
        payments_title.setObjectName("sectionTitle")
        payments_layout.addWidget(payments_title)
        payments_hint = QLabel("Activa únicamente las formas de pago disponibles en tu negocio.")
        payments_hint.setObjectName("pageSubtitle")
        payments_hint.setWordWrap(True)
        payments_hint.setMinimumWidth(0)
        payments_layout.addWidget(payments_hint)
        payments_layout.addWidget(QLabel("Efectivo: siempre habilitado"))
        payments_layout.addWidget(self.transfer)
        payments_layout.addWidget(self.card)

        backup_card = QFrame()
        backup_card.setObjectName("contentCard")
        backup_layout = QVBoxLayout(backup_card)
        backup_layout.setContentsMargins(20, 18, 20, 18)
        backup_title = QLabel("Respaldo y recuperación")
        backup_title.setObjectName("sectionTitle")
        backup_layout.addWidget(backup_title)
        backup_hint = QLabel(
            "Protege la información de tu negocio con una copia local. "
            "Restaurar reemplaza los datos actuales."
        )
        backup_hint.setObjectName("pageSubtitle")
        backup_hint.setWordWrap(True)
        backup_layout.addWidget(backup_hint)
        backup_actions = QHBoxLayout()
        backup_button = QPushButton("Crear respaldo")
        backup_button.clicked.connect(self.create_backup)
        restore_button = QPushButton("Restaurar respaldo")
        restore_button.clicked.connect(self.restore_backup)
        backup_actions.addWidget(backup_button)
        backup_actions.addWidget(restore_button)
        backup_actions.addStretch()
        backup_layout.addLayout(backup_actions)

        layout.addWidget(business_card)
        layout.addWidget(payments_card)
        layout.addWidget(backup_card)
        layout.addWidget(self.message)
        layout.addStretch()

    def save(self) -> None:
        methods = ["cash"]
        if self.transfer.isChecked():
            methods.append("transfer")
        if self.card.isChecked():
            methods.append("card")
        try:
            self.settings.update(
                self.business_id,
                self.name.text(),
                self.currency.text(),
                self.threshold.value(),
                tuple(methods),
                self.tax_rate.text(),
            )
        except ValueError as error:
            QMessageBox.warning(self, "No se puede guardar", str(error))
            return
        self.message.setText(f"Configuración de {self.name.text().strip()} actualizada.")

    def create_backup(self) -> None:
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar respaldo",
            str(Path.home() / "SuiteLocal-respaldo.sqlite"),
            "Base SQLite (*.sqlite *.db);;Todos los archivos (*)",
        )
        if not destination:
            return
        try:
            path = create_backup(self.database, destination)
        except BackupError as error:
            QMessageBox.warning(self, "No se pudo crear el respaldo", str(error))
            return
        self.message.setText(f"Respaldo creado: {path.name}.")

    def restore_backup(self) -> None:
        source, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar respaldo",
            str(Path.home()),
            "Base SQLite (*.sqlite *.db);;Todos los archivos (*)",
        )
        if not source:
            return
        answer = QMessageBox.question(
            self,
            "Confirmar restauración",
            "La restauración reemplazará los datos actuales del negocio. ¿Deseas continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            safety_path = (
                self.database.path.parent
                / "backups"
                / f"antes-restauracion-{datetime.now():%Y%m%d-%H%M%S}.sqlite"
            )
            restore_backup(self.database, source, safety_path)
        except BackupError as error:
            QMessageBox.warning(self, "No se pudo restaurar", str(error))
            return
        self.message.setText(
            "Restauración completada. "
            f"Copia de seguridad previa: {safety_path.name}. "
            "Reinicia SuiteLocal para cargar los datos restaurados."
        )
