# JSON Editor UX Audit — April 2026

Tracked improvements for the control editor UI. Check off items as they're completed.

## High Impact

- [x] **A. Validation error below the fold** — Moved validation error alert above the editor (between toolbar and editor) so it's visible without scrolling.

- [x] **B. No inline error highlighting in editor** — Added Monaco deltaDecorations for server validation errors: red wavy underline + hover message on the offending JSON value. Uses jsonc-parser to resolve API field paths to editor ranges.

- [x] **C. Decision enum: can't see all values without clearing** — Set `filterText` to the current node value so Monaco's fuzzy matching shows all enum options regardless of cursor position inside the existing value.

## Medium Impact

- [ ] **D. No unsaved changes warning** — Clicking X or Cancel with unsaved changes silently discards everything. **Fix:** Show a "Discard unsaved changes?" confirm dialog if the user made edits.

- [ ] **E. Editor height is fixed at 520px** — Short controls waste space; long controls require internal scrolling + dialog scrolling (double scroll). **Fix:** Consider auto-sizing the editor to content (with min/max), or making the dialog full-height with the editor taking remaining space.

- [ ] **F. No keyboard shortcut for Save** — Must click the button or tab to it. **Fix:** Cmd+S / Ctrl+S should trigger Save from within the editor.

- [ ] **G. Step name dropdown says "No steps available"** — The agent has no registered steps, so the dropdown is empty and disabled. **Fix:** Show a more helpful message like "Register steps via SDK to filter by name" or link to docs.

## Polish

- [ ] **H. Form/JSON radio labels are small** — The toggle is a tiny segmented control in the corner. Could benefit from a tooltip explaining Form = guided editing, JSON = full control.

- [ ] **I. No undo/redo buttons** — Only keyboard shortcuts work (Ctrl+Z). Toolbar redo/undo icons would improve discoverability.

- [ ] **J. Auto-generated control names are long** — `json-control-for-test-agent-break-ui` is 37 chars. Consider shorter defaults like `list-control-1`.

## Completed

- [x] **Empty control name silently blocks save** — Added `noValidate` + explicit `validateField('name')` so Mantine shows "Control name is required" error.
- [x] **Double-click Confirm creates duplicate 409** — Close confirm modal immediately on first click via `modals.close(modalId)`.
- [x] **Form/JSON toggle stuck disabled on validation errors** — Only disable for JSON parse errors, not server validation errors.
- [x] **Control name lost during mode switches** — Preserve `definitionForm.values.name` instead of resetting to `control.name`.
- [x] **Snippet cursor placed after quotes** — Use `"$1"` tab stop in string property snippets.
- [x] **`$schema` in suggestions** — Suppress Monaco's built-in JSON completions via `setModeConfiguration` + schema override.
- [x] **Typing `"` doesn't trigger autocomplete** — Auto-trigger when `"` typed at property-key position.
