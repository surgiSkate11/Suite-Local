# UI/UX polish (Fase 5)

Polish SuiteLocal's PySide6 UI: fix UI bugs, keyboard/focus, feedback (toasts, inline errors), contrast, consistency and transitions.
Worktree `C:\Users\daybu\Downloads\SuiteLocal-ui`, branch `feat/ui-polish`. Do not edit `suitelocal/infrastructure/`, `suitelocal/application/`, `suitelocal/domain/` (another session owns security fixes). UI tests run offscreen (`QT_QPA_PLATFORM=offscreen`), no new dependencies.

## Specs

- S1 User request: "quiero un puylido y perfeccionamiento de la ui, ux y demas".
- S2 Planned phase (PROGRESS.md): "Fase 5 — Pulido: atajos, foco, toasts, transiciones, contraste y capturas visuales."
- S3 Bugs: Caja shortcuts (`Delete`, `F2`) and refresh/focus run inside `_relayout` (pos.py) and must run once; `Ctrl+Enter` must also accept `Ctrl+Return`; "Cerrar sesión" must return to login (DESIGN §4), not quit the app.
- S4 Contrast: text and component token pairs meet WCAG AA (4.5:1 text, 3:1 input borders); DESIGN.md §2.1 updated to match; no hard-coded colors outside tokens in `ui/`.
- S5 Feedback: success/error toasts via a host in the shell (DESIGN §6) replace routine `QMessageBox` feedback; inline messages show error state in red; destructive confirmations use Spanish "Sí"/"No" labels with "No" default.
- S6 Keyboard & focus: `Esc` closes the open drawer; `Enter` submits Inventory/Users/Settings forms; focus moves to the first field when a drawer opens and to the main field when switching page; `Ctrl+K` focuses Caja search when Caja is active; `↑`/`↓` in Caja search move the result selection; icon-only buttons have `accessibleName`.
- S7 Drawer: heading shows its title ("Editar producto"/"Nuevo producto"); closes and clears after a successful save.
- S8 Consistency: one primary action per view; secondary/danger button variants; no text glyph icons (`×`, `→`, `✓`) where DESIGN §2.4 requires SVG.
- S9 Transitions: animated sidebar collapse and toast fade (DESIGN §2.5), respecting short durations.
- S10 Captures at 1100 and 1440 px and PROGRESS.md updated.

## Tasks

- [ ] T1 S3 — fix Caja shortcut/relayout bug, Ctrl+Return, logout→login loop; tests/test_ui_pos.py, tests/test_ui_shell.py — inline — commit: 
- [ ] T2 S4 — contrast tokens, inline error state, hard-coded colors → tokens; DESIGN.md — inline — commit: 
- [ ] T3 S5 — ToastHost, replace routine QMessageBox, Spanish confirmations — inline — commit: 
- [ ] T4 S6, S7 — Esc/Enter/focus/arrows/accessibleName; drawer title and close-after-save — inline — commit: 
- [ ] T5 S8 — button variants, SVG icons instead of glyphs — inline — commit: 
- [ ] T6 S9 — sidebar and toast animations — inline — commit: 
- [ ] T7 S10 — captures, PROGRESS.md — inline — commit: 

## Log

- L1 (user, verbatim): "continua, quiero un puylido y perfeccionamiento de la ui, ux y demas"
- L2 User chose a separate worktree (`SuiteLocal-ui`, branch `feat/ui-polish`) so the other session (security fixes on `fix/hallazgos-revision`) is not affected.
- L3 Read-only audit (gentle-ai-explore) produced the gap list behind S3–S10; out of scope here: features needing new repository methods (recent sales list, inventory filter/pagination).
