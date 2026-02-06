# Integration Tests

This directory contains Playwright integration tests for the UI. Tests run against a Next.js dev server with mocked API responses.

## Test Structure

```
tests/
├── fixtures.ts              # Mock data and API route mocking setup
├── home.spec.ts            # Home page tests
├── agent-detail.spec.ts    # Agent detail page tests
├── control-store.spec.ts   # Control store modal tests
└── evaluators/             # Evaluator form tests
    ├── helpers.ts          # Shared helpers for evaluator tests
    ├── regex.spec.ts
    ├── list.spec.ts
    ├── json.spec.ts
    ├── sql.spec.ts
    └── luna2.spec.ts
```

## Running Tests

```bash
# Run all tests (requires dev server running)
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

## CI Integration

Tests run automatically in GitHub Actions on every push/PR. The CI:

- Starts the Next.js dev server
- Installs Playwright browsers
- Runs all tests
- Uploads test reports on failure
