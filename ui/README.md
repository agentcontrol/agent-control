# Agent Control UI

Next.js dashboard for managing [Agent Control](https://github.com/agentcontrol/agent-control) agents and controls. Runs on port 4000.

## Prerequisites

- **Node.js 20+** (CI uses 20; 18+ may work)
- **pnpm 9+** — install from [pnpm.io](https://pnpm.io/) or run `corepack enable && corepack prepare pnpm@latest --activate`

For full functionality (e.g. live data, regenerating API types), the Agent Control server must be running. See the [main README](../README.md#quick-start) for server setup.

## Tech Stack

- **Next.js 15** (Pages Router) + **React 19** + **TypeScript**
- **Mantine 7** + **Jupiter DS** (Galileo's design system)
- **TanStack Query** for server state management
- **openapi-fetch** with auto-generated types from the server's OpenAPI spec

## Quick Start

```bash
pnpm install
pnpm dev              # starts on http://localhost:4000
```

To regenerate API types from a running server:

```bash
pnpm fetch-api-types  # fetches from http://localhost:8000/openapi.json
```

## Folder Structure

```
src/
├── pages/                 # Next.js routes
│   ├── _app.tsx           # App wrapper (providers, global styles)
│   ├── index.tsx          # Home page (agents list)
│   ├── agents/
│   │   ├── [id].tsx       # Agent detail page
│   │   └── [id]/          # Agent sub-routes
│   │       ├── controls.tsx
│   │       └── monitor.tsx
├── core/
│   ├── api/               # API client + auto-generated types
│   │   ├── client.ts      # openapi-fetch client with typed methods
│   │   ├── generated/     # Auto-generated from OpenAPI spec
│   │   └── types.ts       # Re-exported type aliases
│   ├── evaluators/        # Evaluator form registry (json, sql, regex, list, luna2)
│   ├── hooks/query-hooks/ # TanStack Query hooks (useAgent, useAgents, etc.)
│   ├── layouts/           # App shell with sidebar navigation
│   ├── page-components/   # Page-level components (home, agent-detail)
│   ├── providers/         # React context providers (QueryProvider)
│   └── types/             # Shared TypeScript types
├── components/            # Reusable UI components (error-boundary, icons)
└── styles/                # Global CSS, fonts
```

## Key Patterns

- **API types are auto-generated** — run `pnpm fetch-api-types` after server API changes
- **Query hooks** wrap the `api` client and return typed data (see `core/hooks/query-hooks/`)
- **Page components** contain the actual UI logic; `pages/` files are thin wrappers that apply layouts
- **Evaluator forms** follow a registry pattern in `core/evaluators/` — each evaluator type (json, sql, regex, list, luna2) has its own folder with `form.tsx`, `types.ts`, and `index.ts`; the edit-control modal uses these via the registry

## Documentation and help

- **Product and API:** [Main README](../README.md), [Reference](https://github.com/agentcontrol/agent-control/blob/main/README.md), and [docs/](../docs/) in the repo.
- **Bugs and feature requests:** [GitHub Issues](https://github.com/agentcontrol/agent-control/issues).
