import { getAgentRoute } from '@/core/constants/agent-routes';

import { expect, mockData, mockRoutes, test } from './fixtures';

test.describe('Agent Monitor Tab', () => {
  test.beforeEach(async ({ mockedPage }) => {
    // Navigate to agent detail page
    await mockedPage.goto(getAgentRoute('agent-1', { tab: 'monitor' }));
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
    await expect(mockedPage.getByText('Recent executions')).toHaveCount(0);
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
    await expect(
      mockedPage.getByText('Observe', { exact: true })
    ).toBeVisible();
    await expect(mockedPage.getByText('Deny', { exact: true })).toBeVisible();
    await expect(mockedPage.getByText('Steer', { exact: true })).toHaveCount(0);
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

  test('should show the latest exact blocked span expanded', async ({
    mockedPage,
  }) => {
    await mockedPage.getByRole('tab', { name: 'Events' }).click();

    await expect(mockedPage.getByText('Recent executions')).toBeVisible();
    await expect(
      mockedPage.getByText('you are now a helpful travel guide', {
        exact: true,
      })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Full content', { exact: true }).first()
    ).toBeVisible();
    await expect(
      mockedPage.getByText('4bf92f3577b34da6a3ce929d0e0e4736', {
        exact: true,
      })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('LOCAL-INJECTION-014', { exact: true })
    ).toBeVisible();
    await expect(mockedPage.getByText('Metadata only')).toBeVisible();
  });

  test('should omit blocked content for a metadata-only span', async ({
    mockedPage,
  }) => {
    await mockRoutes.events(mockedPage, {
      data: {
        ...mockData.events,
        total: 1,
        events: [mockData.events.events[1]],
      },
    });
    await mockedPage.reload();
    await mockedPage.getByRole('tab', { name: 'Events' }).click();

    await expect(mockedPage.getByText('Metadata only')).toBeVisible();
    await expect(mockedPage.getByText('Blocked input')).toHaveCount(0);
    await expect(
      mockedPage.getByText('Full content', { exact: true })
    ).toHaveCount(0);
  });

  test('labels included content as redacted when the event reports redaction', async ({
    mockedPage,
  }) => {
    const fullContentEvent = mockData.events.events[0];
    await mockRoutes.events(mockedPage, {
      data: {
        ...mockData.events,
        total: 1,
        events: [
          {
            ...fullContentEvent,
            control_execution_id: 'execution-redacted',
            metadata: {
              ...fullContentEvent.metadata,
              content_unredacted: false,
            },
          },
        ],
      },
    });
    await mockedPage.reload();
    await mockedPage.getByRole('tab', { name: 'Events' }).click();

    await expect(
      mockedPage.getByText('Redacted content', { exact: true }).first()
    ).toBeVisible();
    await expect(
      mockedPage.getByText('you are now a helpful travel guide', {
        exact: true,
      })
    ).toBeVisible();
    await expect(mockedPage.getByText('Full content')).toHaveCount(0);
    await expect(mockedPage.getByText('Metadata only')).toHaveCount(0);
  });

  test('does not infer a privacy state for built-in evaluator events', async ({
    mockedPage,
  }) => {
    await mockRoutes.events(mockedPage, {
      data: {
        ...mockData.events,
        total: 1,
        events: [
          {
            ...mockData.events.events[1],
            control_execution_id: 'execution-regex',
            control_name: 'Regex policy',
            evaluator_name: 'regex',
            metadata: { request_id: 'request-regex' },
          },
        ],
      },
    });
    await mockedPage.reload();
    await mockedPage.getByRole('tab', { name: 'Events' }).click();

    await expect(mockedPage.getByText('Regex policy')).toBeVisible();
    await expect(mockedPage.getByText('regex', { exact: true })).toBeVisible();
    await expect(mockedPage.getByText('Metadata only')).toHaveCount(0);
    await expect(mockedPage.getByText('Full content')).toHaveCount(0);
    await expect(mockedPage.getByText('Redacted content')).toHaveCount(0);
  });

  test('should distinguish an event API failure from an empty result', async ({
    mockedPage,
  }) => {
    await mockRoutes.events(mockedPage, {
      error: 'Event query failed',
      status: 500,
    });
    await mockedPage.reload();
    await mockedPage.getByRole('tab', { name: 'Events' }).click();

    await expect(
      mockedPage.getByText('Failed to load recent executions.')
    ).toBeVisible();
    await expect(
      mockedPage.getByText(
        'Exact control spans will appear here as they are received.'
      )
    ).toHaveCount(0);
  });
});

test.describe('Agent Monitor Tab - Empty State', () => {
  test('should show empty state when no stats available', async ({ page }) => {
    await mockRoutes.config(page);
    // Set up mocks with empty stats
    await mockRoutes.agents(page);
    await mockRoutes.agent(page);
    await mockRoutes.stats(page, { data: mockData.emptyStats });
    await mockRoutes.events(page, {
      data: { events: [], total: 0, limit: 20, offset: 0 },
    });

    // Navigate to agent detail page
    await page.goto(getAgentRoute('agent-1', { tab: 'monitor' }));
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
    await mockRoutes.config(page);
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
          observe_count: 5,
          deny_count: 5,
          steer_count: 0,
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
          observe_count: 15,
          deny_count: 20,
          steer_count: 0,
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
    await page.goto(getAgentRoute('agent-1', { tab: 'monitor' }));
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
    await mockRoutes.config(page);
    // Set up mocks with failing stats endpoint
    await mockRoutes.agents(page);
    await mockRoutes.agent(page);
    await mockRoutes.stats(page, {
      error: 'Internal server error',
      status: 500,
    });

    // Navigate to agent detail page
    await page.goto(getAgentRoute('agent-1', { tab: 'monitor' }));
    await expect(
      page.getByRole('heading', { name: 'customer-support-bot' })
    ).toBeVisible();

    // Navigate to stats tab
    await page.getByRole('tab', { name: 'Monitor' }).click();

    // Should show error state
    await expect(page.getByText('Failed to load stats')).toBeVisible();
  });
});
