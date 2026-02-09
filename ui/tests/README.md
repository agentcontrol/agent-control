# Integration Tests

This directory contains Playwright integration tests for the UI. Tests run against a Next.js dev server with mocked API responses.

## Test Structure

```
tests/
├── fixtures.ts              # Mock data and API route mocking setup
├── home.spec.ts             # Home page tests
├── agent-detail.spec.ts     # Agent detail page tests
├── agent-stats.spec.ts      # Agent stats / monitor tests
├── control-store.spec.ts    # Control store modal tests
├── search-input.spec.ts    # SearchInput component tests
├── step-name-input.spec.ts  # Step name input tests
└── evaluators/              # Evaluator form tests
    ├── helpers.ts           # Shared helpers for evaluator tests
    ├── regex.spec.ts
    ├── list.spec.ts
    ├── json.spec.ts
    ├── sql.spec.ts
    └── luna2.spec.ts
```

## Running Tests

```bash
# Run all tests (locally: ensure dev server is running, or use production build)
pnpm test:integration

# Run with UI mode (interactive)
pnpm test:integration:ui

# Run in headed mode (see browser)
pnpm test:integration:headed

# Debug mode
pnpm test:integration:debug

# View last test report
pnpm test:integration:report
```

## Test Patterns

### Mock Data

- All mock data is typed using generated API types (`@/core/api/types`)
- Mock data is centralized in `fixtures.ts`
- Type safety ensures tests break if backend API changes

### API Mocking

- Uses Playwright's `page.route()` to intercept API calls
- `mockedPage` fixture automatically sets up all route mocks
- Individual tests can override mocks for specific scenarios

### Selectors

- Prefer semantic selectors: `getByRole()`, `getByText()`, `getByTestId()`
- Use `{ exact: true }` when text might match multiple elements
- Scope selectors to modals/dialogs when needed

### Test Organization

- Group related tests with `test.describe()`
- Use descriptive test names that explain what is being tested
- Keep tests focused on single behaviors

## Adding New Tests

1. **For new pages**: Create `tests/[page-name].spec.ts`
2. **For new components**: Add tests to the relevant page spec or create component-specific tests
3. **For new evaluators**: Add `tests/evaluators/[evaluator-name].spec.ts`

### Example Test

```typescript
import { expect, test } from './fixtures';

test.describe('My Feature', () => {
  test('does something', async ({ mockedPage }) => {
    await mockedPage.goto('/my-page');
    await expect(mockedPage.getByText('Expected text')).toBeVisible();
  });
});
```

## Reporting issues

If you see flaky or failing tests that don’t reproduce locally, please open an issue on the [GitHub repository](https://github.com/agentcontrol/agent-control/issues) with the failing run link and any relevant logs.

## CI Integration

Tests run automatically in GitHub Actions on every push/PR. The CI:

- Installs dependencies and runs lint + Prettier check + typecheck
- Builds the Next.js app (production build)
- Installs Playwright browsers (Chromium)
- Runs all integration tests against the production build
- Uploads Playwright report and test results on failure
