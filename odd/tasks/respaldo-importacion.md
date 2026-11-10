# Respaldo automático e importación de productos (T14 of odd/tasks/rediseno-multinegocio.md)

Daily automatic backup to a chosen folder plus CSV product import, for the Ecuador SuiteLocal app.
Branch `feat/respaldo-importacion` from `feat/multinegocio` 27133d7, worktree `C:\Users\daybu\Downloads\SuiteLocal-ui`. Assigned by peer session 01a1a49b, who merges and runs a native review on the backup part.

## Specs

- S1 Parent spec S18: "Respaldo automático diario a una carpeta elegida (pendrive o carpeta de nube), conservando los últimos 7, más importar productos desde CSV/Excel exportado."
- S2 Backup (peer, verbatim): "Settings > "Respaldo y recuperación" gets a folder picker (injected), "Respaldar automáticamente cada día" (default off) and "Conservar los últimos N" (default 7); uses the existing create_backup (Connection.backup, never file copy); runs at startup and every hour from a QTimer but only once per calendar day, off the UI thread and never overlapping; prunes the oldest copies beyond N, only files matching our own name pattern; shows "Último respaldo: dd/mm hh:mm" in the status bar (persisted in settings); one warning toast on failure."
- S3 Import (peer, verbatim): "accept Excel-exported CSV (UTF-8 with BOM or cp1252, ";" or "," delimiter) with columns código, nombre, precio, stock and optional categoría, costo, IVA; a preview dialog shows how many will be created/updated and per-row errors before confirming; owner only; everything in one transaction (all or nothing); prices use the business decimal separator; unknown categories are created; "Importar productos" button in Inventario."
- S4 Rules (peer, verbatim): "test-first, Spanish UI strings with voseo, English identifiers, no new dependencies, prefix every command with `timeout`, no real dialogs, leave no python process; ruff, pyright and the full suite at the end; commit on your branch with Conventional Commits in Spanish and send me the ids. Do not push."

## Tasks

- [x] T1 S2, S4 — automatic daily backup (infrastructure, settings persistence, Settings UI, status bar) — worker A, parent commits — commit: 05ea782
- [x] T2 S3, S4 — CSV product import (parser, application service, preview dialog, Inventario button) — worker B, parent commits — commit: 4f234f1
- [ ] T3 S4 — full checks, commit, send ids to 01a1a49b — inline — commit: n/a

## Log

- L1 User: "continua con las tareas que faltan". Peer assigned T14 with the scope in S2-S4 and told us to branch from the fiado commit 27133d7.
- L2 T1 and T2 are independent units with disjoint files, so they run as two parallel workers that do not commit; the parent commits each one separately.
- L3 Both workers died with "child exit unconfirmed" after writing their code. T1 was complete (50 tests). T2 lacked the Inventario wiring; the parent added it inline (8 UI tests were RED) and aligned one UI test with the service message that includes the line number. The old shell test asserting no backup text in the status bar was updated: it now asserts the honest "Último respaldo: nunca".
- L4 Peer asked (after review of the plan): do not repeat the failure toast every hour; like the SRI runner, warn once per distinct failure and again only after a success; keep the failure visible in the status bar as "Último respaldo: falló dd/mm hh:mm". Done in a separate fix commit with tests.
