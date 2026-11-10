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
    ,receipt_paper_mm INTEGER NOT NULL DEFAULT 80 CHECK (receipt_paper_mm IN (58, 80))
    ,printer_name TEXT NOT NULL DEFAULT ''
    ,einvoice_enabled INTEGER NOT NULL DEFAULT 0 CHECK (einvoice_enabled IN (0, 1))
    ,sri_environment TEXT NOT NULL DEFAULT 'pruebas'
        CHECK (sri_environment IN ('pruebas', 'produccion'))
    ,establishment TEXT NOT NULL DEFAULT '001'
    ,emission_point TEXT NOT NULL DEFAULT '001'
    ,obligado_contabilidad INTEGER NOT NULL DEFAULT 0 CHECK (obligado_contabilidad IN (0, 1))
    ,trade_name TEXT NOT NULL DEFAULT ''
    ,print_on_charge INTEGER NOT NULL DEFAULT 1 CHECK (print_on_charge IN (0, 1))
    ,auto_backup_enabled INTEGER NOT NULL DEFAULT 0 CHECK (auto_backup_enabled IN (0, 1))
    ,auto_backup_folder TEXT NOT NULL DEFAULT ''
    ,auto_backup_keep INTEGER NOT NULL DEFAULT 7 CHECK (auto_backup_keep >= 1)
    ,last_auto_backup_at TEXT
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

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    id_type TEXT NOT NULL CHECK (id_type IN ('cedula', 'ruc', 'pasaporte')),
    id_number TEXT NOT NULL,
    full_name TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    accepts_offers INTEGER NOT NULL DEFAULT 0 CHECK (accepts_offers IN (0, 1)),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    ,credit_limit_cents INTEGER CHECK (credit_limit_cents IS NULL OR credit_limit_cents >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_business_id_number
    ON customers(business_id, id_number);

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
    method TEXT NOT NULL CHECK (method IN ('cash', 'transfer', 'card', 'credit')),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    reference TEXT NOT NULL DEFAULT ''
);

-- Credit (fiado) account of each customer: a cargo is a credit sale, an abono a payment on it.
-- The balance is the cargos minus the abonos. A cash abono belongs to the open cash session.
CREATE TABLE IF NOT EXISTS customer_ledger (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    kind TEXT NOT NULL CHECK (kind IN ('cargo', 'abono')),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    sale_id INTEGER REFERENCES sales(id),
    method TEXT CHECK (method IS NULL OR method IN ('cash', 'transfer')),
    note TEXT NOT NULL DEFAULT '',
    user_id INTEGER NOT NULL REFERENCES users(id),
    cash_session_id INTEGER REFERENCES cash_sessions(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_customer_ledger_customer
    ON customer_ledger(business_id, customer_id, id);
CREATE INDEX IF NOT EXISTS idx_customer_ledger_cash_session
    ON customer_ledger(cash_session_id) WHERE cash_session_id IS NOT NULL;

-- Last sequential handed out per business, environment, establishment and emission point.
CREATE TABLE IF NOT EXISTS einvoice_sequences (
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    environment TEXT NOT NULL CHECK (environment IN ('pruebas', 'produccion')),
    establishment TEXT NOT NULL,
    emission_point TEXT NOT NULL,
    last_sequential INTEGER NOT NULL CHECK (last_sequential BETWEEN 0 AND 999999999),
    PRIMARY KEY (business_id, environment, establishment, emission_point)
);
"""

# The send queue of SRI electronic invoices: one row per invoice. A sale has at most one active
# row; a refused invoice that is re-issued stays as "reemplazada" and points to its successor.
# It is built by code, not by SCHEMA, because adding a status to a CHECK needs a table rebuild.
_EINVOICES_TABLE = """
CREATE TABLE {name} (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    sale_id INTEGER NOT NULL REFERENCES sales(id),
    establishment TEXT NOT NULL,
    emission_point TEXT NOT NULL,
    sequential TEXT NOT NULL,
    access_key TEXT NOT NULL UNIQUE,
    environment TEXT NOT NULL CHECK (environment IN ('pruebas', 'produccion')),
    status TEXT NOT NULL DEFAULT 'pendiente' CHECK (
        status IN (
            'pendiente', 'recibida', 'devuelta', 'autorizada', 'no_autorizada', 'error_local',
            'reemplazada'
        )
    ),
    signed_xml BLOB NOT NULL,
    buyer_id_type TEXT NOT NULL,
    buyer_identification TEXT NOT NULL,
    buyer_name TEXT NOT NULL,
    buyer_address TEXT NOT NULL DEFAULT '',
    messages TEXT NOT NULL DEFAULT '[]',
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at TEXT,
    issued_at TEXT NOT NULL,
    authorized_at TEXT,
    authorization_number TEXT,
    replaced_by INTEGER REFERENCES einvoices(id),
    UNIQUE (business_id, environment, establishment, emission_point, sequential)
)
"""
# Every column of the table before `replaced_by` existed, in storage order.
_EINVOICES_OLD_COLUMNS = (
    "id, business_id, sale_id, establishment, emission_point, sequential, access_key, "
    "environment, status, signed_xml, buyer_id_type, buyer_identification, buyer_name, "
    "buyer_address, messages, attempts, next_attempt_at, issued_at, authorized_at, "
    "authorization_number"
)
_EINVOICES_REBUILT = "einvoices_rebuilt"
_EINVOICES_COPY = (
    f"INSERT INTO {_EINVOICES_REBUILT} ({_EINVOICES_OLD_COLUMNS}) "
    f"SELECT {_EINVOICES_OLD_COLUMNS} FROM einvoices"
)
_EINVOICES_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_einvoices_status ON einvoices(status, next_attempt_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_einvoices_active_sale "
    "ON einvoices(sale_id) WHERE status <> 'reemplazada'",
)
_EINVOICES_COPY_FAILED = (
    "La migración de las facturas electrónicas no copió todas las filas y se deshizo. "
    "No se perdió ningún dato."
)


_SALE_PAYMENTS_COPY_FAILED = (
    "La migración de los pagos no copió todas las filas y se deshizo. No se perdió ningún dato."
)


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
            _migrate_sales(connection)
            _migrate_einvoices(connection)
            _migrate_sale_payments(connection)
            add_missing_columns(
                connection,
                "customers",
                (
                    "credit_limit_cents INTEGER CHECK (credit_limit_cents IS NULL "
                    "OR credit_limit_cents >= 0)",
                ),
            )
            # Left NULL on old sales: they were priced with the tax added on top, so a
            # per-line IVA cannot be derived from them and they are never rewritten.
            add_missing_columns(
                connection,
                "sale_items",
                ("tax_rate_basis_points INTEGER", "tax_cents INTEGER"),
            )
        # Imported here because tables_repository itself imports this module. It runs after the
        # block above: the script it executes commits, so it could not sit inside that transaction.
        from suitelocal.infrastructure.tables_repository import ensure_tables_schema

        with self.connect() as connection:
            ensure_tables_schema(connection)


def add_missing_columns(
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


def _migrate_sales(connection: sqlite3.Connection) -> None:
    added = add_missing_columns(
        connection,
        "sales",
        (
            "subtotal_cents INTEGER NOT NULL DEFAULT 0",
            "tax_cents INTEGER NOT NULL DEFAULT 0",
            "tax_rate_basis_points INTEGER NOT NULL DEFAULT 0",
            "cash_session_id INTEGER REFERENCES cash_sessions(id)",
            "business_id INTEGER REFERENCES businesses(id)",
            "user_id INTEGER REFERENCES users(id)",
            "sales_note_number TEXT",
            "customer_id INTEGER REFERENCES customers(id)",
        ),
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_sales_customer ON sales(customer_id)")
    if "business_id" not in added:
        return
    # Old sales never recorded their business. The cash session knows it; what is left belongs
    # to the only business of the installation. Runs only when the column is created, so a
    # sale registered later without a business stays NULL and is never claimed by anyone.
    # user_id stays NULL on old sales: nobody recorded who sold them.
    connection.execute(
        """
        UPDATE sales
        SET business_id = (SELECT business_id FROM cash_sessions WHERE id = sales.cash_session_id)
        WHERE cash_session_id IS NOT NULL
        """
    )
    businesses = connection.execute("SELECT id FROM businesses LIMIT 2").fetchall()
    if len(businesses) == 1:
        connection.execute(
            "UPDATE sales SET business_id = ? WHERE business_id IS NULL", (businesses[0]["id"],)
        )


def _migrate_sale_payments(connection: sqlite3.Connection) -> None:
    """Rebuild an old `sale_payments` whose CHECK does not accept the "credit" method.

    Runs inside the caller's transaction; nothing else references the table. The copy is
    checked row for row before the old table goes away, and any failure rolls everything back.
    """
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'sale_payments'"
    ).fetchone()
    if row is None or "'credit'" in row["sql"]:
        return
    columns = "id, sale_id, method, amount_cents, reference"
    connection.execute("DROP TABLE IF EXISTS sale_payments_rebuilt")
    connection.execute(
        """
        CREATE TABLE sale_payments_rebuilt (
            id INTEGER PRIMARY KEY,
            sale_id INTEGER NOT NULL REFERENCES sales(id),
            method TEXT NOT NULL CHECK (method IN ('cash', 'transfer', 'card', 'credit')),
            amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
            reference TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute(
        f"INSERT INTO sale_payments_rebuilt ({columns}) SELECT {columns} FROM sale_payments"
    )
    unmatched = connection.execute(
        f"SELECT COUNT(*) FROM (SELECT {columns} FROM sale_payments "
        f"EXCEPT SELECT {columns} FROM sale_payments_rebuilt)"
    ).fetchone()[0]
    if unmatched:
        raise RuntimeError(_SALE_PAYMENTS_COPY_FAILED)
    connection.execute("DROP TABLE sale_payments")
    connection.execute("ALTER TABLE sale_payments_rebuilt RENAME TO sale_payments")


def _migrate_einvoices(connection: sqlite3.Connection) -> None:
    """Create `einvoices`, or rebuild an old one so a sale can have replaced rows.

    Runs inside the caller's transaction. The rebuild copies every row into a new table, checks
    that nothing was lost, drops the old table and renames the new one; any failure raises and
    the caller's rollback leaves the old table exactly as it was. Once the table has
    `replaced_by` there is nothing to do, so running it again changes nothing.
    """
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(einvoices)")}
    if not columns:
        connection.execute(_EINVOICES_TABLE.format(name="einvoices"))
    elif "replaced_by" not in columns:
        connection.execute(f"DROP TABLE IF EXISTS {_EINVOICES_REBUILT}")
        connection.execute(_EINVOICES_TABLE.format(name=_EINVOICES_REBUILT))
        connection.execute(_EINVOICES_COPY)
        old_rows = connection.execute("SELECT COUNT(*) FROM einvoices").fetchone()[0]
        new_rows = connection.execute(f"SELECT COUNT(*) FROM {_EINVOICES_REBUILT}").fetchone()[0]
        # Counting is not enough: any old row without an identical twin is a lost row.
        unmatched = connection.execute(
            f"SELECT COUNT(*) FROM (SELECT {_EINVOICES_OLD_COLUMNS} FROM einvoices "
            f"EXCEPT SELECT {_EINVOICES_OLD_COLUMNS} FROM {_EINVOICES_REBUILT})"
        ).fetchone()[0]
        if old_rows != new_rows or unmatched:
            raise RuntimeError(_EINVOICES_COPY_FAILED)
        connection.execute("DROP TABLE einvoices")
        connection.execute(f"ALTER TABLE {_EINVOICES_REBUILT} RENAME TO einvoices")
    for statement in _EINVOICES_INDEXES:
        connection.execute(statement)


def _migrate_settings(connection: sqlite3.Connection) -> None:
    add_missing_columns(
        connection,
        "business_settings",
        ("tax_rate_basis_points INTEGER NOT NULL DEFAULT 0", "ruc TEXT NOT NULL DEFAULT ''"),
    )
    added = add_missing_columns(
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
            "receipt_paper_mm INTEGER NOT NULL DEFAULT 80 CHECK (receipt_paper_mm IN (58, 80))",
            "printer_name TEXT NOT NULL DEFAULT ''",
            "einvoice_enabled INTEGER NOT NULL DEFAULT 0 CHECK (einvoice_enabled IN (0, 1))",
            "sri_environment TEXT NOT NULL DEFAULT 'pruebas' "
            "CHECK (sri_environment IN ('pruebas', 'produccion'))",
            "establishment TEXT NOT NULL DEFAULT '001'",
            "emission_point TEXT NOT NULL DEFAULT '001'",
            "obligado_contabilidad INTEGER NOT NULL DEFAULT 0 "
            "CHECK (obligado_contabilidad IN (0, 1))",
            "trade_name TEXT NOT NULL DEFAULT ''",
            "print_on_charge INTEGER NOT NULL DEFAULT 1 CHECK (print_on_charge IN (0, 1))",
            "auto_backup_enabled INTEGER NOT NULL DEFAULT 0 CHECK (auto_backup_enabled IN (0, 1))",
            "auto_backup_folder TEXT NOT NULL DEFAULT ''",
            "auto_backup_keep INTEGER NOT NULL DEFAULT 7 CHECK (auto_backup_keep >= 1)",
            "last_auto_backup_at TEXT",
        ),
    )
    if "tax_regime" in added:
        # A business that already identified itself with a RUC keeps operating as a
        # general-regime taxpayer; the rest start as "sin registro".
        connection.execute("UPDATE business_settings SET tax_regime = 'general' WHERE ruc <> ''")


def _migrate_products(connection: sqlite3.Connection) -> None:
    added = add_missing_columns(
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
