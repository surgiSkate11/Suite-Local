import pytest

from suitelocal.core.plugins import ModuleManifest, ModuleRegistry, create_default_registry


def test_default_registry_contains_core_and_future_modules():
    registry = create_default_registry()

    assert [module.key for module in registry.enabled(("pos", "credit"))] == [
        "pos",
        "credit",
    ]


def test_registry_rejects_duplicate_modules():
    registry = ModuleRegistry()
    manifest = ModuleManifest("custom", "Personalizado", "Módulo", "use_custom")
    registry.register(manifest)

    with pytest.raises(ValueError, match="ya está registrado"):
        registry.register(manifest)
