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

- [x] T1 S3 — fix Caja shortcut/relayout bug, Ctrl+Return, logout→login loop; tests/test_ui_pos.py, tests/test_ui_shell.py — inline — commit: 5ed9301
- [x] T2 S4 — contrast tokens, hard-coded colors → tokens; DESIGN.md; tests/test_ui_theme.py — inline — commit: 79bb945
- [x] T3 S5 — InlineMessage error state, ToastHost (bottom-right, 4 s, persistent opt-in), page `notification` signals, Spanish confirmations; tests/test_ui_feedback.py — inline — commit: 51693c5
- [x] T4 S6, S7 — Esc/Enter/focus/arrows/accessibleName, Ctrl+1..5, Ctrl+K per page; drawer title and close-after-save; tests/test_ui_keyboard.py — inline — commit: 40779f6
- [x] T5 S8 — button variants (variant property, DangerButton, set_variant), one primary per view in inventory/users/settings, restore = danger, login check glyph → SVG, exact price text (L6); tests/test_ui_buttons.py — inline (worker failed with no changes) — commit: (this commit)
- [ ] T6 S9 — sidebar and toast animations — inline — commit: 
- [ ] T7 S10 — captures, PROGRESS.md — inline — commit: 

## Log

- L1 (user, verbatim): "continua, quiero un puylido y perfeccionamiento de la ui, ux y demas"
- L2 User chose a separate worktree (`SuiteLocal-ui`, branch `feat/ui-polish`) so the other session (security fixes on `fix/hallazgos-revision`) is not affected.
- L3 Read-only audit (gentle-ai-explore) produced the gap list behind S3–S10; out of scope here: features needing new repository methods (recent sales list, inventory filter/pagination).
- L4 GGA on T1 noted dead `paid` sum in `pos.py::_refresh_payment_status` and duplicated placeholder/header setup; fold into T5 cleanup.
- L5 Offscreen captures render without fonts (tofu); T7 captures must use the real Windows platform.
- L6 GGA on T3: `inventory.load_selected` formats price via float (`price_cents / 100`); fold into T5 cleanup with L4.
- L7 Context backstop reached after T4; T5/T6 delegated to a worker.
- L8 Peer session 01a1a49b: POS redesign (design/caja-multinegocio, branch feat/multinegocio, task T9) will reimplement suitelocal/ui/pos.py and likely shell/theme. Freeze pos.py until they say which direction; keep token changes minimal. Database.connect() is now a context manager on their branches.
- L9 Peer 01a1a49b: direction chosen = design/caja-multinegocio/01-grid-tactil.html; peer owns suitelocal/ui/pos.py and new screens (cash register, reports). Allowed for us: polish of login/inventory/users/settings and theme tokens keeping the brand-blue tokens. Tell the peer before touching shell.py. L4 (pos.py cleanup) dropped.
- L10 T5 worker (gentle-ai-worker) failed with an assistant error and left no changes; done inline.
