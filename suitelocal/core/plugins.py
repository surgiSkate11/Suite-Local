from collections.abc import Callable
from dataclasses import dataclass

PageFactory = Callable[[], object]


@dataclass(frozen=True, slots=True)
class ModuleManifest:
    key: str
    label: str
    description: str
    required_permission: str


class ModuleRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, ModuleManifest] = {}

    def register(self, manifest: ModuleManifest) -> None:
        if not manifest.key.strip():
            raise ValueError("Un módulo debe tener una clave.")
        if manifest.key in self._modules:
            raise ValueError(f"El módulo {manifest.key} ya está registrado.")
        self._modules[manifest.key] = manifest

    def get(self, key: str) -> ModuleManifest:
        try:
            return self._modules[key]
        except KeyError as error:
            raise ValueError(f"El módulo {key} no está registrado.") from error

    def available(self) -> tuple[ModuleManifest, ...]:
        return tuple(self._modules.values())

    def enabled(self, keys: tuple[str, ...]) -> tuple[ModuleManifest, ...]:
        return tuple(manifest for manifest in self._modules.values() if manifest.key in keys)


def create_default_registry() -> ModuleRegistry:
    registry = ModuleRegistry()
    registry.register(ModuleManifest("pos", "Caja", "Ventas y cobros", "sell"))
    registry.register(
        ModuleManifest("inventory", "Inventario", "Productos y existencias", "manage_inventory")
    )
    registry.register(
        ModuleManifest("reports", "Reportes", "Indicadores y análisis", "view_reports")
    )
    registry.register(
        ModuleManifest(
            "credit", "Clientes y crédito", "Fiado y cuentas por cobrar", "manage_credit"
        )
    )
    registry.register(
        ModuleManifest("sri_xml", "XML del SRI", "Importación de comprobantes", "import_sri")
    )
    registry.register(
        ModuleManifest("attendance", "Asistencia", "Control de asistencia", "manage_attendance")
    )
    registry.register(
        ModuleManifest("local_ai", "IA local", "Consultas con documentos locales", "use_ai")
    )
    return registry
