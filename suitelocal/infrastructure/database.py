import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    stock INTEGER NOT NULL CHECK (stock >= 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS business_settings (
    business_id INTEGER PRIMARY KEY REFERENCES businesses(id),
    currency_symbol TEXT NOT NULL DEFAULT '$',
    low_stock_threshold INTEGER NOT NULL DEFAULT 3 CHECK (low_stock_threshold >= 0),
    enabled_payment_methods TEXT NOT NULL DEFAULT 'cash,transfer'
    ,tax_rate_basis_points INTEGER NOT NULL DEFAULT 0
        CHECK (tax_rate_basis_points BETWEEN 0 AND 10000)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'cashier')),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

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
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0)
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

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(business_settings)")
            }
            if "tax_rate_basis_points" not in columns:
                connection.execute(
                    """
                    ALTER TABLE business_settings
                    ADD COLUMN tax_rate_basis_points INTEGER NOT NULL DEFAULT 0
                    """
                )
            sale_columns = {row["name"] for row in connection.execute("PRAGMA table_info(sales)")}
            for column in (
                "subtotal_cents INTEGER NOT NULL DEFAULT 0",
                "tax_cents INTEGER NOT NULL DEFAULT 0",
                "tax_rate_basis_points INTEGER NOT NULL DEFAULT 0",
            ):
                name = column.split()[0]
                if name not in sale_columns:
                    connection.execute(f"ALTER TABLE sales ADD COLUMN {column}")
