import { expect, mockData, test } from './fixtures';

test.describe('SearchInput - Query Param Syncing', () => {
  test('syncs search value to URL query param', async ({ mockedPage }) => {
    await mockedPage.goto('/');

    const searchInput = mockedPage.getByPlaceholder('Search agents...');

    // Type in search input
    await searchInput.fill('Customer');

    // Wait for debounced URL update (300ms)
    await mockedPage.waitForTimeout(350);

    // Verify URL has the query param
    await expect(mockedPage).toHaveURL(/.*\?search=Customer/);
  });

  test('reads search value from URL query param on page load', async ({
    mockedPage,
  }) => {
    // Navigate with query param
    await mockedPage.goto('/?search=Customer');

    // Wait for API response with the search filter
    await mockedPage.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/agents') &&
        response.url().includes('name=Customer') &&
        response.status() === 200
    );

    // Wait for page to load
    await expect(mockedPage.getByRole('table')).toBeVisible();

    // Verify search input has the value from URL
    const searchInput = mockedPage.getByPlaceholder('Search agents...');
    await expect(searchInput).toHaveValue('Customer');

    // Verify filtered results are shown
    await expect(mockedPage.getByText('customer-support-bot')).toBeVisible();
  });

  test('clear button removes query param from URL', async ({ mockedPage }) => {
    await mockedPage.goto('/?search=Customer');

    // Wait for page to load
    await expect(mockedPage.getByRole('table')).toBeVisible();

    const searchInput = mockedPage.getByPlaceholder('Search agents...');
    await expect(searchInput).toHaveValue('Customer');

    // Find and click the clear button (X icon)
    const clearButton = mockedPage.getByTestId('search-clear-search');
    await clearButton.click();

    // Wait for URL update
    await mockedPage.waitForTimeout(100);

    // Verify query param is removed from URL
    await expect(mockedPage).toHaveURL(/\/(\?|$)/); // URL should not have search param

    // Verify search input is cleared
    await expect(searchInput).toHaveValue('');

    // Verify all agents are shown again
    for (const agent of mockData.agents.agents) {
      await expect(mockedPage.getByText(agent.agent_name)).toBeVisible();
    }
  });

  test('preserves search state on browser back/forward', async ({
    mockedPage,
  }) => {
    await mockedPage.goto('/');

    // Type search
    const searchInput = mockedPage.getByPlaceholder('Search agents...');
    await searchInput.fill('Customer');

    // Wait for debounced URL update and API response
    await mockedPage.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/agents') &&
        response.url().includes('name=Customer') &&
        response.status() === 200
    );

    // Navigate away
    await mockedPage.getByText('customer-support-bot').click();
    await expect(mockedPage).toHaveURL(
      /\/agents\/customer-support-bot\/monitor/
    );

    // Go back
    await mockedPage.goBack();

    // Wait for page to load and URL to be correct
    await expect(mockedPage).toHaveURL(/.*\?search=Customer/);

    // Wait for table to be visible (page loaded)
    await expect(mockedPage.getByRole('table')).toBeVisible();

    // Re-get the search input after navigation (element might be recreated)
    const searchInputAfterBack =
      mockedPage.getByPlaceholder('Search agents...');
    await expect(searchInputAfterBack).toHaveValue('Customer');

    // Verify filtered results are still shown
    await expect(mockedPage.getByText('customer-support-bot')).toBeVisible();
  });
});

test.describe('SearchInput - Agent Detail Page', () => {
  test('syncs search value to URL query param (q)', async ({ mockedPage }) => {
    await mockedPage.goto('/agents/agent-1/controls');

    const searchInput = mockedPage.getByPlaceholder('Search controls...');
    await searchInput.fill('PII');

    // Wait for debounced URL update
    await mockedPage.waitForTimeout(350);

    // Verify URL has the query param (uses 'q' key)
    await expect(mockedPage).toHaveURL(/.*\?q=PII/);
  });

  test('reads search value from URL on page load', async ({ mockedPage }) => {
    await mockedPage.goto('/agents/agent-1/controls?q=PII');

    // Wait for page to load
    await expect(mockedPage.getByRole('table')).toBeVisible();

    // Verify search input has the value from URL (client-side filtering, so no API wait needed)
    const searchInput = mockedPage.getByPlaceholder('Search controls...');
    await expect(searchInput).toHaveValue('PII');

    // Verify filtered results are shown (PII Detection should be visible in the controls table)
    // Use a more specific selector to avoid the stats tab
    const controlsTable = mockedPage.getByRole('table');
    await expect(controlsTable.getByText('PII Detection')).toBeVisible();
  });
});
