# JSON Editor UX Audit — April 2026

Tracked improvements for the control editor UI. Check off items as they're completed.

## High Impact

- [x] **A. Validation error below the fold** — Moved validation error alert above the editor (between toolbar and editor) so it's visible without scrolling.

- [x] **B. No inline error highlighting in editor** — Added Monaco deltaDecorations for server validation errors: red wavy underline + hover message on the offending JSON value. Uses jsonc-parser to resolve API field paths to editor ranges.

- [x] **C. Decision enum: can't see all values without clearing** — Set `filterText` to the current node value so Monaco's fuzzy matching shows all enum options regardless of cursor position inside the existing value.

## Medium Impact

- [x] **D. No unsaved changes warning** — Cancel in edit mode now shows "Discard unsaved changes?" confirmation if the user made edits. Tracks dirty state via `isDirty` flag and `definitionForm.isDirty()`.

- [ ] **E. Editor height is fixed at 520px** — Short controls waste space; long controls require internal scrolling + dialog scrolling (double scroll). **Fix:** Consider auto-sizing the editor to content (with min/max), or making the dialog full-height with the editor taking remaining space.

- [x] **F. Cmd+S / Ctrl+S keyboard shortcut** — Triggers Save from anywhere in the edit dialog via `formRef.requestSubmit()`.

- [x] **G. Step name placeholder** — Changed from "No steps available" to "No steps registered via SDK" for better guidance.

## Polish

- [x] **H. Form/JSON toggle tooltip** — Added tooltip: "Form: guided editing. Full JSON: direct control over the definition."

- [ ] **I. No undo/redo buttons** — Only keyboard shortcuts work (Ctrl+Z). Toolbar redo/undo icons would improve discoverability.

- [x] **J. Shorter default control names** — Changed from `list-control-for-agent-name` to `new-list-control`.

## Completed

- [x] **Empty control name silently blocks save** — Added `noValidate` + explicit `validateField('name')` so Mantine shows "Control name is required" error.
- [x] **Double-click Confirm creates duplicate 409** — Close confirm modal immediately on first click via `modals.close(modalId)`.
- [x] **Form/JSON toggle stuck disabled on validation errors** — Only disable for JSON parse errors, not server validation errors.
- [x] **Control name lost during mode switches** — Preserve `definitionForm.values.name` instead of resetting to `control.name`.
- [x] **Snippet cursor placed after quotes** — Use `"$1"` tab stop in string property snippets.
- [x] **`$schema` in suggestions** — Suppress Monaco's built-in JSON completions via `setModeConfiguration` + schema override.
- [x] **Typing `"` doesn't trigger autocomplete** — Auto-trigger when `"` typed at property-key position.
