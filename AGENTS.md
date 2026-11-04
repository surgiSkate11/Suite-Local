# SuiteLocal

Sistema de ventas e inventario offline para pequeñas empresas. Python 3.12 + PySide6 (Qt) + SQLite.

## Comandos (PowerShell, desde la raíz)

- Instalar: `python -m pip install -e ".[dev]"`
- Ejecutar: `python -m suitelocal.main` (opcional `--database <ruta>`)
- Tests (suite): `python -m pytest -q`
- Tests (un módulo): `python -m pytest tests/test_sales.py -q`
- Lint: `python -m ruff check .`
- Formato: `python -m ruff format .`
- Tipos: `python -m pyright`

No hay virtualenv: se usa el Python 3.12 global.

## Estructura

- `suitelocal/domain/`: modelos, políticas y reglas de negocio (sin Qt).
- `suitelocal/application/`: casos de uso (auth, carrito, inventario), sin dependencia de Qt.
- `suitelocal/infrastructure/`: SQLite, repositorios, respaldos, seguridad, terminal de pago.
- `suitelocal/ui/`: vistas PySide6 (`theme/`, `components/`, `dev/gallery.py`).
- `suitelocal/core/plugins.py`: sistema de plugins.
- `tests/`: pytest, un archivo por área.

## Reglas

- Ruff con línea de 100; Pyright en modo `strict` sobre `suitelocal/`. Ambos deben quedar en cero y el código formateado con `ruff format`.
- Dinero siempre como enteros en centavos.
- `domain` y `application` no importan Qt.
- Respaldos con `Connection.backup()` de SQLite, nunca copiando el archivo.
- Actualizá `PROGRESS.md` al cerrar una fase o decisión.
- No leas `.env` ni archivos de credenciales.
- No agregues dependencias sin preguntar; fijá versiones en `pyproject.toml`.
- Antes de decir "listo", corré los tests de lo que tocaste y mostrá el resultado.

La fuente de verdad de arquitectura es `docs/ARCHITECTURE.md`; requisitos en `docs/REQUIREMENTS.md` y diseño en `docs/DESIGN.md`.
