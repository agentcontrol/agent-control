# UI: instructions for coding agents

This document is for **contributors and coding agents** working on the Agent Control UI. It describes conventions, patterns, and how to make common changes. For repository-wide workflow (branch naming, commits, PRs), see the [Contributing guide](../CONTRIBUTING.md) in the repo root.

Next.js 15 app (Pages Router) with React 19, TypeScript, Mantine 7, and TanStack Query.

## Quick commands

```bash
pnpm install          # install deps
pnpm dev              # dev server on http://localhost:4000
pnpm build            # production build
pnpm lint             # lint
pnpm lint:fix         # lint + auto-fix
pnpm typecheck        # TypeScript check
pnpm prettify         # format all files with Prettier
pnpm prettify:check   # check formatting (CI)
pnpm fetch-api-types  # regenerate API types from server (must be running on :8000)
```

## Code conventions

- **TypeScript**: strict mode, no `any` unless unavoidable
- **Imports**: use `@/` alias (maps to `src/`), keep imports sorted (eslint auto-fixes)
- **Components**: functional components only, use named exports
- **Styling**: Mantine components + Jupiter DS; avoid inline styles, use Mantine's `style` props or CSS modules
- **State**: server state via TanStack Query hooks; local state via `useState`

### Jupiter DS (Galileo's design system)

- `@rungalileo/jupiter-ds` — Galileo's component library built on top of Mantine
- Provides themed components: `Button`, `Table`, `Switch`, etc.
- `JupiterThemeProvider` wraps the app in `_app.tsx` (inside MantineProvider)
- **When to use**: prefer Jupiter DS components over Mantine equivalents when available — they have Galileo's styling baked in
- **Fallback**: for components not in Jupiter DS, use Mantine directly — they're compatible since Jupiter DS extends Mantine

## Key patterns

### API layer (`core/api/`)

- Types are **auto-generated** from OpenAPI — run `pnpm fetch-api-types` after server changes
- `client.ts` exports typed `api` object with namespaced methods (`api.agents.get()`, `api.controls.create()`, etc.)
- **NEVER use raw `fetch()` for API calls** — always add new endpoints to the `api` object in `client.ts`. This ensures consistent base URL handling, auth headers, and type safety.
- Never call `apiClient` directly in components; use the `api` wrapper or query hooks
- **Best practice**: always derive types from `generated/api-types.ts` — this keeps types flowing from backend to frontend for tight integration; avoid duplicating or manually defining types that already exist in the generated file
- **Debugging tip**: if you hit type errors related to API responses/requests, regenerate types first (`pnpm fetch-api-types`) — they may be stale

### Query hooks (`core/hooks/query-hooks/`)

- One hook per query/mutation (e.g., `useAgent`, `useCreateControl`)
- Hooks wrap `api` calls and return typed TanStack Query results
- Query keys follow pattern: `["resource", id]` or `["resource", "list", params]`

### Page structure

- `pages/` — thin route files that apply layouts and import page components
- `core/page-components/` — actual page UI logic lives here
- `core/layouts/` — app shell, sidebar navigation

### Evaluator forms (`core/evaluators/`)

- Each evaluator type has its own folder: `json/`, `sql/`, `regex/`, `list/`, `luna2/`
- Each folder exports: `form.tsx` (React component), `types.ts` (form types), `index.ts` (re-exports)
- Registry in `evaluators/index.ts` maps evaluator names to form components

### Form guidelines (control definition + evaluator forms)

- **Always use the input's `label` prop** — never render a separate `<Text>` above the input as the label. Use Mantine's built-in `label` so required asterisks and layout are consistent.
- **Label with tooltip**: Use `LabelWithTooltip` from `@/core/components/label-with-tooltip` when a field needs an (i) icon that shows help text on hover. Pass `label={<LabelWithTooltip label="Field name" tooltip="Help text..." />}` and, for inputs that support it, `labelProps={labelPropsInline}` so the label renders inline.
- **Required fields**: Use the input's `required` prop (e.g. Select, TextInput) so Mantine renders the red asterisk. Use `labelPropsInline` from the same module when you need the label inline.
- Applies to: control definition form (`edit-control/control-definition-form.tsx`) and all evaluator forms (`core/evaluators/*/form.tsx`).

### Reusable components (`core/components/`)

- Create reusable components that encapsulate common patterns and logic
- **Best practice**: When creating wrapper components around Mantine components, extend the underlying component's props using `Omit` to exclude overridden props, then spread `...rest` to forward all other props
- This provides full flexibility while maintaining type safety

**Example: SearchInput component pattern**

```typescript
import type { TextInputProps } from "@mantine/core";
import { TextInput } from "@mantine/core";

interface SearchInputProps
  extends Omit<TextInputProps, "value" | "onChange" | "leftSection" | "rightSection"> {
  queryKey: string; // Required prop specific to this component
}

export function SearchInput({
  queryKey,
  placeholder = "Search...",
  w = 250,
  ...rest // Forward all other TextInput props
}: SearchInputProps) {
  // Component logic...
  return (
    <TextInput
      {...rest} // Spread all forwarded props
      // Override specific props
      value={searchQuery}
      onChange={handleChange}
    />
  );
}
```

**Benefits:**

- Full type safety for all underlying component props
- No need to explicitly define every prop in the wrapper interface
- Easy to extend with new props from the underlying component
- Maintains backward compatibility when underlying component adds new props

## Common changes

### Add a new evaluator form

1. Create folder in `core/evaluators/<name>/`
2. Add `types.ts` with form field types
3. Add `form.tsx` with the form component — use Mantine form components with `label` prop and `LabelWithTooltip` from `@/core/components/label-with-tooltip` for fields that need a tooltip (see Form guidelines above)
4. Add `index.ts` re-exporting form and types
5. Register in `evaluators/index.ts`

### Add a new API endpoint integration

1. Run `pnpm fetch-api-types` to get new types from the server
2. Add method to `api` object in `core/api/client.ts` (e.g., `api.observability.getStats()`)
3. Add query hook in `core/hooks/query-hooks/` that calls the `api` method
4. Use hook in component
5. Import types from `@/core/api/generated/api-types` — never manually define request/response types

### Add a new page

1. Create route file in `pages/` (e.g., `pages/settings.tsx`)
2. Create page component in `core/page-components/<name>/`
3. Apply layout via `getLayout` pattern (see existing pages)
