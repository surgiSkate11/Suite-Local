# Mesas y comandas (T8 of odd/tasks/rediseno-multinegocio.md)

Open accounts per table for cafés/restaurants, sent to kitchen and charged at the end, without tips. Ecuador only (USD, cents).
Branch `feat/mesas` from `feat/multinegocio` da20a1d, worktree `C:\Users\daybu\Downloads\SuiteLocal-ui`. Requested by peer session 01a1a49b on behalf of the user; confirmed by the user in this session.

## Specs

- S1 Scope: "T8 "Mesas y comandas" for cafés/restaurants, WITHOUT tips (the user explicitly removed tips: "si es propina dejalo ya q eso es un regalo para el empleado")". "Product is for Ecuador only (USD, cents)." Parent spec: odd/tasks/rediseno-multinegocio.md (S5, S10, L20, L21).
- S2 Domain/application (no Qt): "tables with a name/number and optional zone; an open order per table; add/remove/change quantity of products on it; mark items "sent to kitchen" (comanda); transfer an order to another table; cancel an open order; close = produce a `Sale` (suitelocal/domain/models.py) charged through the EXISTING SaleRepository.register path (do not duplicate stock or payment logic). Stock is only decremented when the order is charged, not when items are added. One open order per table."
- S3 Persistence: "your own module suitelocal/infrastructure/tables_repository.py with a `TABLES_SCHEMA` constant and `ensure_tables_schema(connection)`; idempotent CREATE TABLE IF NOT EXISTS." "Your tests call ensure_tables_schema after Database.initialize()." `Database.connect()` is a context manager: always `with database.connect() as c:`.
- S4 UI: "suitelocal/ui/tables.py with a `TablesWidget` (floor grid of tables: libre / ocupada with amount and minutes open; selected table's order panel; "Enviar a cocina", "Cobrar mesa" which reuses suitelocal/ui/payment_dialog.py through an injectable factory). Use current_tokens()/theme_changed for anything painted in Python, no hex outside tokens.py, Spanish UI strings with voseo like the rest of the app, English identifiers."
- S5 Tax agnostic: "the cart will change soon so that IVA is extracted from tax-included prices instead of added on top. Keep the tables code agnostic: build the Sale from SaleItem lines + payments and let the existing domain compute totals."
- S6 Tests: "Tests (test-first) in tests/test_tables.py and tests/test_ui_tables.py. Use tests/conftest.py (it releases widgets after each test); wrap commands with `timeout`, never call .exec() on real dialogs."
- S7 Boundaries: "Allowed files: suitelocal/domain/tables.py, suitelocal/application/tables.py, suitelocal/infrastructure/tables_repository.py, suitelocal/ui/tables.py, tests/test_tables.py, tests/test_ui_tables.py. Anything else: ask me first." "DO NOT edit suitelocal/infrastructure/database.py, repositories.py, models.py, cart.py, settings.py or shell.py". (This tracking file odd/tasks/mesas.md is new and only ours.)
- S8 Done: "Finish with ruff format, ruff check, pyright and the full pytest suite green; commit on feat/mesas with Conventional Commits in Spanish and send me the commit ids. Do not push."

## Tasks

- [x] T1 S1-S3, S5, S6 — domain + application + tables_repository; tests/test_tables.py — worker — commit: 4613ecc
- [x] T2 S4, S6 — TablesWidget; tests/test_ui_tables.py — worker — commit: d4a1164
- [x] T3 S8 — full checks, send commit ids to 01a1a49b — inline — commit: n/a

## Log

- L1 (peer 01a1a49b, relaying the user's T8 assignment; full message): New task for you from the user (Edwin): T8 "Mesas y comandas" for cafés/restaurants, WITHOUT tips. Base feat/multinegocio da20a1d, branch feat/mesas. Scope, persistence, UI, tests, allowed files and done criteria as quoted in S1-S8.
- L2 User confirmed in this session: "Sí, hacela".
- L3 T1 done 4613ecc. Worker flagged: charge() registers the sale and closes the order in two transactions (possible double charge under concurrency; fix needs repositories.py, peer-owned); charge does not require an open cash session.
- L4 T2 worker built and verified the UI, then failed at commit; parent re-ran checks (351 passed) and committed d4a1164. Commit ids sent to peer 01a1a49b with open points (double-charge race, no cash-session check, ProductRepository imported from UI).
