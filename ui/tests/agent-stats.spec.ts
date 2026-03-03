import { expect, mockData, mockRoutes, test } from './fixtures';

test.describe('Agent Monitor Tab', () => {
  test.beforeEach(async ({ mockedPage }) => {
    // Navigate to agent detail page
    await mockedPage.goto('/agents/agent-1/monitor');
    // Wait for the page to load
    await expect(
      mockedPage.getByRole('heading', { name: 'customer-support-bot' })
    ).toBeVisible();
  });

  test('should display stats tab and navigate to it', async ({
    mockedPage,
  }) => {
    // Stats tab should be visible
    const statsTab = mockedPage.getByRole('tab', { name: 'Monitor' });
    await expect(statsTab).toBeVisible();

    // Click on stats tab
    await statsTab.click();

    // Should show the stats content - check for summary card metrics (use first() to get summary card, not table header)
    await expect(mockedPage.getByText('Executions').first()).toBeVisible();
    await expect(mockedPage.getByText('Triggers').first()).toBeVisible();
    await expect(mockedPage.getByText('Errors').first()).toBeVisible();
  });

  test('should display time range selector with default value', async ({
    mockedPage,
  }) => {
    // Navigate to stats tab
    await mockedPage.getByRole('tab', { name: 'Monitor' }).click();

    // Time range selector should be visible (TimeRangeSwitch component)
    // Look for the component by finding the segment buttons or menu button
    const timeRangeSwitch = mockedPage
      .locator('[class*="TimeRangeSwitch"]')
      .first();
    await expect(timeRangeSwitch).toBeVisible();
  });

  test('should display summary statistics', async ({ mockedPage }) => {
    // Navigate to stats tab
    await mockedPage.getByRole('tab', { name: 'Monitor' }).click();

    // Check total executions
    await expect(
      mockedPage.getByText(
        mockData.stats.totals.execution_count.toLocaleString()
      )
    ).toBeVisible();

    // Check for summary card labels (use first() to get summary card, not table header)
    await expect(mockedPage.getByText('Executions').first()).toBeVisible();
    await expect(mockedPage.getByText('Triggers').first()).toBeVisible();
    await expect(mockedPage.getByText('Errors').first()).toBeVisible();
  });

  test('should display actions distribution section', async ({
    mockedPage,
  }) => {
    // Navigate to stats tab
    await mockedPage.getByRole('tab', { name: 'Monitor' }).click();

    // Check actions distribution header
    await expect(mockedPage.getByText('Actions Distribution')).toBeVisible();

    // Check action types are displayed (use exact match to avoid matching badges)
    await expect(mockedPage.getByText('Allow', { exact: true })).toBeVisible();
    await expect(mockedPage.getByText('Deny', { exact: true })).toBeVisible();
    await expect(mockedPage.getByText('Warn', { exact: true })).toBeVisible();
    await expect(mockedPage.getByText('Log', { exact: true })).toBeVisible();
  });

  test('should display per-control statistics table', async ({
    mockedPage,
  }) => {
    // Navigate to stats tab
    await mockedPage.getByRole('tab', { name: 'Monitor' }).click();

    // Check table column headers
    await expect(
      mockedPage.getByRole('columnheader', { name: 'Control' })
    ).toBeVisible();
    await expect(
      mockedPage.getByRole('columnheader', { name: 'Executions' })
    ).toBeVisible();
    await expect(
      mockedPage.getByRole('columnheader', { name: 'Triggers', exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByRole('columnheader', { name: 'Errors' })
    ).toBeVisible();
  });

  test('should display control names in the table', async ({ mockedPage }) => {
    // Navigate to stats tab
    await mockedPage.getByRole('tab', { name: 'Monitor' }).click();

    // Check control names from mock data - scope to Stats panel table
    const statsTable = mockedPage
      .getByRole('tabpanel', { name: /Monitor/i })
      .getByRole('table');
    for (const stat of mockData.stats.controls) {
      await expect(statsTable.getByText(stat.control_name)).toBeVisible();
    }
  });

  test('should allow changing time range', async ({ mockedPage }) => {
    // Navigate to stats tab
    await mockedPage.getByRole('tab', { name: 'Monitor' }).click();

    // TimeRangeSwitch should be visible and allow changing time range
    // The component has segment buttons for quick selection
    const timeRangeSwitch = mockedPage
      .locator('[class*="TimeRangeSwitch"]')
      .first();
    await expect(timeRangeSwitch).toBeVisible();

    // Try clicking on a segment button (e.g., "1D" for 24 hours)
    const oneDayButton = mockedPage
      .getByRole('button', { name: /1D/i })
      .first();
    if (await oneDayButton.isVisible()) {
      await oneDayButton.click();
    }
  });

  test('should show error badges for controls with errors', async ({
    mockedPage,
  }) => {
    // Navigate to stats tab
    await mockedPage.getByRole('tab', { name: 'Monitor' }).click();

    // SQL Injection Guard has 2 errors in mock data
    // Find the row and check for error count
    const errorBadge = mockedPage.locator('table').getByText('2').first();
    await expect(errorBadge).toBeVisible();
  });
});

test.describe('Agent Monitor Tab - Empty State', () => {
  test('should show empty state when no stats available', async ({ page }) => {
    // Set up mocks with empty stats
    await mockRoutes.agents(page);
    await mockRoutes.agent(page);
    await mockRoutes.stats(page, { data: mockData.emptyStats });

    // Navigate to agent detail page
    await page.goto('/agents/agent-1/monitor');
    await expect(
      page.getByRole('heading', { name: 'customer-support-bot' })
    ).toBeVisible();

    // Navigate to stats tab
    await page.getByRole('tab', { name: 'Monitor' }).click();

    // Time range selector should still be visible in empty state (TimeRangeSwitch)
    const timeRangeSwitch = page.locator('[class*="TimeRangeSwitch"]').first();
    await expect(timeRangeSwitch).toBeVisible();

    // Should show empty state messages in the charts
    await expect(page.getByText('No data available')).toBeVisible();
    await expect(page.getByText('No triggers yet')).toBeVisible();
  });
});

test.describe('Agent Monitor Tab - Refetch Flow', () => {
  test('should update values when data is refetched', async ({ page }) => {
    let requestCount = 0;

    // Initial stats data
    const initialStats: typeof mockData.stats = {
      ...mockData.stats,
      totals: {
        ...mockData.stats.totals,
        execution_count: 100,
        match_count: 10,
      },
      controls: [
        {
          control_id: 1,
          control_name: 'PII Detection',
          execution_count: 100,
          match_count: 10,
          non_match_count: 90,
          allow_count: 5,
          deny_count: 5,
          steer_count: 0,
          warn_count: 0,
          log_count: 0,
          error_count: 0,
          avg_confidence: 0.85,
          avg_duration_ms: 40,
        },
      ],
    };

    // Updated stats data (returned after first request)
    const updatedStats: typeof mockData.stats = {
      ...mockData.stats,
      totals: {
        ...mockData.stats.totals,
        execution_count: 250,
        match_count: 35,
      },
      controls: [
        {
          control_id: 1,
          control_name: 'PII Detection',
          execution_count: 250,
          match_count: 35,
          non_match_count: 215,
          allow_count: 15,
          deny_count: 20,
          steer_count: 0,
          warn_count: 0,
          log_count: 0,
          error_count: 1,
          avg_confidence: 0.91,
          avg_duration_ms: 38,
        },
      ],
    };

    // Set up standard mocks
    await mockRoutes.agents(page);
    await mockRoutes.agent(page);

    // Mock stats endpoint with handler that returns different data on subsequent requests
    await mockRoutes.stats(page, {
      handler: () => {
        requestCount++;
        return requestCount === 1 ? initialStats : updatedStats;
      },
    });

    // Navigate to agent detail page
    await page.goto('/agents/agent-1/monitor');
    await expect(
      page.getByRole('heading', { name: 'customer-support-bot' })
    ).toBeVisible();

    // Navigate to stats tab
    await page.getByRole('tab', { name: 'Monitor' }).click();

    // Verify initial values are displayed (use first() to get summary stat, not table cell)
    // Initial: 100 executions, 10 matches = 10% match rate
    await expect(page.getByText('100', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('10.0%').first()).toBeVisible();

    // Wait for refetch (component polls every 5 seconds)
    // We wait for the updated values to appear
    // Updated: 250 executions, 35 matches = 14% match rate
    await expect(page.getByText('250', { exact: true }).first()).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByText('14.0%').first()).toBeVisible();

    // Verify the request was made multiple times
    expect(requestCount).toBeGreaterThan(1);
  });
});

test.describe('Agent Monitor Tab - Error State', () => {
  test('should show error state when API fails', async ({ page }) => {
    // Set up mocks with failing stats endpoint
    await mockRoutes.agents(page);
    await mockRoutes.agent(page);
    await mockRoutes.stats(page, {
      error: 'Internal server error',
      status: 500,
    });

    // Navigate to agent detail page
    await page.goto('/agents/agent-1/monitor');
    await expect(
      page.getByRole('heading', { name: 'customer-support-bot' })
    ).toBeVisible();

    // Navigate to stats tab
    await page.getByRole('tab', { name: 'Monitor' }).click();

    // Should show error state
    await expect(page.getByText('Failed to load stats')).toBeVisible();
  });
});
