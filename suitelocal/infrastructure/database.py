import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

REQUIRED_TABLES = frozenset({"businesses", "business_settings", "users", "products", "sales"})

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_business_name
    ON categories(business_id, name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    stock INTEGER NOT NULL CHECK (stock >= 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    category_id INTEGER REFERENCES categories(id),
    cost_cents INTEGER CHECK (cost_cents IS NULL OR cost_cents >= 0),
    tax_rate_basis_points INTEGER NOT NULL DEFAULT 1500
        CHECK (tax_rate_basis_points IN (1500, 500, 0))
);

CREATE TABLE IF NOT EXISTS business_settings (
    business_id INTEGER PRIMARY KEY REFERENCES businesses(id),
    currency_symbol TEXT NOT NULL DEFAULT '$',
    low_stock_threshold INTEGER NOT NULL DEFAULT 3 CHECK (low_stock_threshold >= 0),
    enabled_payment_methods TEXT NOT NULL DEFAULT 'cash,transfer'
    ,tax_rate_basis_points INTEGER NOT NULL DEFAULT 1500
        CHECK (tax_rate_basis_points BETWEEN 0 AND 10000)
    ,ruc TEXT NOT NULL DEFAULT ''
    ,tax_regime TEXT NOT NULL DEFAULT 'sin_registro'
    ,business_type TEXT NOT NULL DEFAULT 'otro'
    ,enabled_modules TEXT NOT NULL DEFAULT ''
    ,decimal_separator TEXT NOT NULL DEFAULT ','
    ,address TEXT NOT NULL DEFAULT ''
    ,phone TEXT NOT NULL DEFAULT ''
    ,receipt_footer TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'cashier')),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS cash_sessions (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    opening_cents INTEGER NOT NULL CHECK (opening_cents >= 0),
    closed_at TEXT,
    counted_cents INTEGER CHECK (counted_cents IS NULL OR counted_cents >= 0),
    expected_cents INTEGER,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_cash_sessions_one_open
    ON cash_sessions(business_id) WHERE closed_at IS NULL;

CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_cents INTEGER NOT NULL CHECK (total_cents >= 0),
    payment_cents INTEGER NOT NULL CHECK (payment_cents >= 0),
    change_cents INTEGER NOT NULL CHECK (change_cents >= 0)
    ,subtotal_cents INTEGER NOT NULL DEFAULT 0 CHECK (subtotal_cents >= 0)
    ,tax_cents INTEGER NOT NULL DEFAULT 0 CHECK (tax_cents >= 0)
    ,tax_rate_basis_points INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sale_items (
    id INTEGER PRIMARY KEY,
    sale_id INTEGER NOT NULL REFERENCES sales(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    product_name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    tax_rate_basis_points INTEGER,
    tax_cents INTEGER
);

CREATE TABLE IF NOT EXISTS sale_payments (
    id INTEGER PRIMARY KEY,
    sale_id INTEGER NOT NULL REFERENCES sales(id),
    method TEXT NOT NULL CHECK (method IN ('cash', 'transfer', 'card')),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    reference TEXT NOT NULL DEFAULT ''
);
"""


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection]:
        """Open a connection that commits on success, rolls back on error and always closes."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            # One transaction for every migration step: DDL is transactional in SQLite, so a
            # failure never leaves a column added without the data fix that goes with it.
            connection.execute("BEGIN IMMEDIATE")
            _migrate_settings(connection)
            _migrate_products(connection)
            _add_missing_columns(
                connection,
                "sales",
                (
                    "subtotal_cents INTEGER NOT NULL DEFAULT 0",
                    "tax_cents INTEGER NOT NULL DEFAULT 0",
                    "tax_rate_basis_points INTEGER NOT NULL DEFAULT 0",
                    "cash_session_id INTEGER REFERENCES cash_sessions(id)",
                ),
            )
            # Left NULL on old sales: they were priced with the tax added on top, so a
            # per-line IVA cannot be derived from them and they are never rewritten.
            _add_missing_columns(
                connection,
                "sale_items",
                ("tax_rate_basis_points INTEGER", "tax_cents INTEGER"),
            )


def _add_missing_columns(
    connection: sqlite3.Connection, table: str, definitions: tuple[str, ...]
) -> set[str]:
    """ALTER-if-missing: add each column definition absent from the table; return added names."""
    existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    added: set[str] = set()
    for definition in definitions:
        name = definition.split()[0]
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
            added.add(name)
    return added


def _migrate_settings(connection: sqlite3.Connection) -> None:
    _add_missing_columns(
        connection,
        "business_settings",
        ("tax_rate_basis_points INTEGER NOT NULL DEFAULT 0", "ruc TEXT NOT NULL DEFAULT ''"),
    )
    added = _add_missing_columns(
        connection,
        "business_settings",
        (
            "tax_regime TEXT NOT NULL DEFAULT 'sin_registro'",
            "business_type TEXT NOT NULL DEFAULT 'otro'",
            "enabled_modules TEXT NOT NULL DEFAULT ''",
            "decimal_separator TEXT NOT NULL DEFAULT ','",
            "address TEXT NOT NULL DEFAULT ''",
            "phone TEXT NOT NULL DEFAULT ''",
            "receipt_footer TEXT NOT NULL DEFAULT ''",
        ),
    )
    if "tax_regime" in added:
        # A business that already identified itself with a RUC keeps operating as a
        # general-regime taxpayer; the rest start as "sin registro".
        connection.execute("UPDATE business_settings SET tax_regime = 'general' WHERE ruc <> ''")


def _migrate_products(connection: sqlite3.Connection) -> None:
    added = _add_missing_columns(
        connection,
        "products",
        (
            "category_id INTEGER REFERENCES categories(id)",
            "cost_cents INTEGER CHECK (cost_cents IS NULL OR cost_cents >= 0)",
            "tax_rate_basis_points INTEGER NOT NULL DEFAULT 1500 "
            "CHECK (tax_rate_basis_points IN (1500, 500, 0))",
        ),
    )
    if "tax_rate_basis_points" not in added:
        return
    # Until now the business had one IVA rate for every product, so each existing product
    # inherits it when it is one of the legal Ecuadorian rates; otherwise 15 % applies.
    # Runs only when the column is created, so later rate edits are never overwritten.
    row = connection.execute(
        "SELECT tax_rate_basis_points FROM business_settings ORDER BY business_id LIMIT 1"
    ).fetchone()
    rate = row["tax_rate_basis_points"] if row is not None else 1500
    if rate not in (1500, 500, 0):
        rate = 1500
    connection.execute("UPDATE products SET tax_rate_basis_points = ?", (rate,))
    # That setting now means "default for new products", so it must be a valid rate too.
    connection.execute(
        "UPDATE business_settings SET tax_rate_basis_points = 1500 "
        "WHERE tax_rate_basis_points NOT IN (1500, 500, 0)"
    )
