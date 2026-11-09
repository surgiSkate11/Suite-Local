# PyInstaller spec: `python -m PyInstaller packaging/suitelocal.spec` (or packaging\build.ps1).
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821  (SPECPATH is provided by PyInstaller)

# Files the app reads from disk at runtime, kept at the same path relative to the package.
datas = [
    (str(ROOT / "suitelocal" / "infrastructure" / "sri" / "xsd"), "suitelocal/infrastructure/sri/xsd"),
]
# Inter font files are optional (the app falls back to Segoe UI); bundle them when present.
fonts = ROOT / "assets" / "fonts"
if fonts.exists():
    datas.append((str(fonts), "assets/fonts"))

a = Analysis(  # noqa: F821
    [str(ROOT / "suitelocal" / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    # lxml is imported by name at runtime (import_module), so the analysis cannot see it.
    hiddenimports=["lxml.etree", "lxml._elementpath"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "pyright", "ruff", "pip"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SuiteLocal",
    console=False,
    icon=str(ROOT / "packaging" / "suitelocal.ico"),
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="SuiteLocal",
    upx=False,
)
