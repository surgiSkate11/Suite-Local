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

- S9 Atomic charge (user: "me aprece mejor q optemos por la atomicidad"; peer option (a), verbatim): "1) Add exactly the `on_registered: Callable[[sqlite3.Connection, int], None] | None = None` hook to SaleRepository.register in repositories.py: called inside the same BEGIN IMMEDIATE transaction after all inserts/stock updates, before commit; no other edits or reformatting in that file (my T4b worker changes only ProductRepository.update there, so the merge stays clean). 2) Adapt TablesService.charge and TablesWidget to the 6c91f0b model: drop the tax_rate_basis_points parameter, build SaleItems that carry each product's IVA rate, show IVA as "IVA incluido $X" via format_usd like pos.py. 3) close_in requiring the order still open + charge passing it as on_registered. Tests: callback raising rolls back everything (no sale row, stock unchanged, order still open, payments absent); second charge of the same order is rejected with a Spanish message and creates no second sale; existing register tests untouched; one table charge at mixed rates (15 % + 0 %) with exact base/IVA/total. Leave the product-search-through-a-service point and the nav wiring to me."
- S10 Allowed files for T4: the S7 list plus suitelocal/infrastructure/repositories.py (only the S9 hook in SaleRepository.register).

## Tasks

- [x] T1 S1-S3, S5, S6 — domain + application + tables_repository; tests/test_tables.py — worker — commit: 4613ecc
- [x] T2 S4, S6 — TablesWidget; tests/test_ui_tables.py — worker — commit: d4a1164
- [x] T3 S8 — full checks, send commit ids to 01a1a49b — inline — commit: n/a

- [x] T4 S9, S10 — rebase onto dbe8fa2 (done), register hook, charge atomic, tax-included IVA per line in tables — worker writes, parent commits — commit: (this commit)

## Log

- L1 (peer 01a1a49b, relaying the user's T8 assignment; full message): New task for you from the user (Edwin): T8 "Mesas y comandas" for cafés/restaurants, WITHOUT tips. Base feat/multinegocio da20a1d, branch feat/mesas. Scope, persistence, UI, tests, allowed files and done criteria as quoted in S1-S8.
- L2 User confirmed in this session: "Sí, hacela".
- L3 T1 done 4613ecc. Worker flagged: charge() registers the sale and closes the order in two transactions (possible double charge under concurrency; fix needs repositories.py, peer-owned); charge does not require an open cash session.
- L4 T2 worker built and verified the UI, then failed at commit; parent re-ran checks (351 passed) and committed d4a1164. Commit ids sent to peer 01a1a49b with open points (double-charge race, no cash-session check, ProductRepository imported from UI).
- L5 Peer chose option (a) with condition: rebase feat/mesas onto dbe8fa2 first (done: db5a54e, 60a1106, 2a3afaf). After rebase 10 tables tests fail and pyright has 2 errors because Sale no longer takes tax_rate_basis_points (SaleItem carries tax_rate_basis_points). Peer will run a native review on the charge commit at merge.
- L6 T4 verified by parent: repositories.py diff limited to the register hook; rollback via Database.connect() except-BaseException rollback; 494 passed, ruff/pyright clean. order_lines gained tax_rate_basis_points (dev DBs with old order_lines need drop or ALTER).
