import { expect, mockData, mockRoutes, test } from "./fixtures";

test.describe("Agent Stats Tab", () => {
  test.beforeEach(async ({ mockedPage }) => {
    // Navigate to agent detail page
    await mockedPage.goto("/agents/agent-1");
    // Wait for the page to load
    await expect(mockedPage.getByText("Customer Support Bot")).toBeVisible();
  });

  test("should display stats tab and navigate to it", async ({ mockedPage }) => {
    // Stats tab should be visible
    const statsTab = mockedPage.getByRole("tab", { name: "Stats" });
    await expect(statsTab).toBeVisible();

    // Click on stats tab
    await statsTab.click();

    // Should show the stats content
    await expect(
      mockedPage.getByRole("heading", { name: "Control Statistics", exact: true })
    ).toBeVisible();
  });

  test("should display time range selector with default value", async ({
    mockedPage,
  }) => {
    // Navigate to stats tab
    await mockedPage.getByRole("tab", { name: "Stats" }).click();

    // Time range selector should be visible with default "Last 1 hour"
    const timeRangeSelect = mockedPage.getByRole("textbox", { name: "Time Range" });
    await expect(timeRangeSelect).toBeVisible();
    await expect(timeRangeSelect).toHaveValue("Last 1 hour");
  });

  test("should display summary statistics", async ({ mockedPage }) => {
    // Navigate to stats tab
    await mockedPage.getByRole("tab", { name: "Stats" }).click();

    // Check total executions
    await expect(
      mockedPage.getByText(mockData.stats.total_executions.toLocaleString())
    ).toBeVisible();

    // Check for badges showing matches and non-matches (use first() to get badge, not table header)
    await expect(mockedPage.getByText("Non-Matches").first()).toBeVisible();
    await expect(mockedPage.getByText("Matches").first()).toBeVisible();
    await expect(mockedPage.getByText("Errors").first()).toBeVisible();
  });

  test("should display actions distribution section", async ({ mockedPage }) => {
    // Navigate to stats tab
    await mockedPage.getByRole("tab", { name: "Stats" }).click();

    // Check actions distribution header
    await expect(mockedPage.getByText("Actions Distribution")).toBeVisible();

    // Check action types are displayed (use exact match to avoid matching badges)
    await expect(mockedPage.getByText("Allow", { exact: true })).toBeVisible();
    await expect(mockedPage.getByText("Deny", { exact: true })).toBeVisible();
    await expect(mockedPage.getByText("Warn", { exact: true })).toBeVisible();
    await expect(mockedPage.getByText("Log", { exact: true })).toBeVisible();
  });

  test("should display per-control statistics table", async ({ mockedPage }) => {
    // Navigate to stats tab
    await mockedPage.getByRole("tab", { name: "Stats" }).click();

    // Check table header
    await expect(
      mockedPage.getByRole("heading", { name: "Per-Control Statistics" })
    ).toBeVisible();

    // Check table column headers (use exact match to avoid "Matches" matching "Non-Matches")
    await expect(mockedPage.getByRole("columnheader", { name: "Control" })).toBeVisible();
    await expect(mockedPage.getByRole("columnheader", { name: "Executions" })).toBeVisible();
    await expect(
      mockedPage.getByRole("columnheader", { name: "Matches", exact: true })
    ).toBeVisible();
    await expect(mockedPage.getByRole("columnheader", { name: "Non-Matches" })).toBeVisible();
    await expect(mockedPage.getByRole("columnheader", { name: "Actions" })).toBeVisible();
    await expect(mockedPage.getByRole("columnheader", { name: "Errors" })).toBeVisible();
    await expect(
      mockedPage.getByRole("columnheader", { name: "Avg Confidence" })
    ).toBeVisible();
  });

  test("should display control names in the table", async ({ mockedPage }) => {
    // Navigate to stats tab
    await mockedPage.getByRole("tab", { name: "Stats" }).click();

    // Check control names from mock data - scope to Stats panel table
    const statsTable = mockedPage.getByRole("tabpanel", { name: /Stats/i }).getByRole("table");
    for (const stat of mockData.stats.stats) {
      await expect(statsTable.getByText(stat.control_name)).toBeVisible();
    }
  });

  test("should allow changing time range", async ({ mockedPage }) => {
    // Navigate to stats tab
    await mockedPage.getByRole("tab", { name: "Stats" }).click();

    // Open time range selector
    const timeRangeSelect = mockedPage.getByRole("textbox", { name: "Time Range" });
    await timeRangeSelect.click();

    // Select a different time range
    await mockedPage.getByRole("option", { name: "Last 24 hours" }).click();

    // Verify the selection changed
    await expect(timeRangeSelect).toHaveValue("Last 24 hours");
  });

  test("should show error badges for controls with errors", async ({
    mockedPage,
  }) => {
    // Navigate to stats tab
    await mockedPage.getByRole("tab", { name: "Stats" }).click();

    // SQL Injection Guard has 2 errors in mock data
    // Find the row and check for error count
    const errorBadge = mockedPage.locator("table").getByText("2").first();
    await expect(errorBadge).toBeVisible();
  });

  test("should show confidence badges with appropriate colors", async ({
    mockedPage,
  }) => {
    // Navigate to stats tab
    await mockedPage.getByRole("tab", { name: "Stats" }).click();

    // Check that confidence percentages are displayed
    // PII Detection has 92% confidence
    await expect(mockedPage.getByText("92%")).toBeVisible();
    // SQL Injection Guard has 88% confidence
    await expect(mockedPage.getByText("88%")).toBeVisible();
    // Rate Limiter has 95% confidence
    await expect(mockedPage.getByText("95%")).toBeVisible();
  });
});

test.describe("Agent Stats Tab - Empty State", () => {
  test("should show empty state when no stats available", async ({ page }) => {
    // Set up mocks with empty stats
    await mockRoutes.agents(page);
    await mockRoutes.agent(page);
    await mockRoutes.stats(page, { data: mockData.emptyStats });

    // Navigate to agent detail page
    await page.goto("/agents/agent-1");
    await expect(page.getByText("Customer Support Bot")).toBeVisible();

    // Navigate to stats tab
    await page.getByRole("tab", { name: "Stats" }).click();

    // Time range selector should still be visible in empty state
    await expect(page.getByRole("textbox", { name: "Time Range" })).toBeVisible();

    // Should show empty state message
    await expect(page.getByText("No stats available")).toBeVisible();
    await expect(
      page.getByText("Stats will appear here once controls are executed.")
    ).toBeVisible();
  });
});

test.describe("Agent Stats Tab - Refetch Flow", () => {
  test("should update values when data is refetched", async ({ page }) => {
    let requestCount = 0;

    // Initial stats data
    const initialStats: typeof mockData.stats = {
      ...mockData.stats,
      total_executions: 100,
      total_matches: 10,
      stats: [
        {
          control_id: 1,
          control_name: "PII Detection",
          execution_count: 100,
          match_count: 10,
          non_match_count: 90,
          allow_count: 5,
          deny_count: 5,
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
      total_executions: 250,
      total_matches: 35,
      stats: [
        {
          control_id: 1,
          control_name: "PII Detection",
          execution_count: 250,
          match_count: 35,
          non_match_count: 215,
          allow_count: 15,
          deny_count: 20,
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
    await page.goto("/agents/agent-1");
    await expect(page.getByText("Customer Support Bot")).toBeVisible();

    // Navigate to stats tab
    await page.getByRole("tab", { name: "Stats" }).click();

    // Verify initial values are displayed (use first() to get summary stat, not table cell)
    await expect(page.getByText("100", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("85%")).toBeVisible();

    // Wait for refetch (component polls every 5 seconds)
    // We wait for the updated values to appear
    await expect(page.getByText("250", { exact: true }).first()).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByText("91%")).toBeVisible();

    // Verify the request was made multiple times
    expect(requestCount).toBeGreaterThan(1);
  });
});

test.describe("Agent Stats Tab - Error State", () => {
  test("should show error state when API fails", async ({ page }) => {
    // Set up mocks with failing stats endpoint
    await mockRoutes.agents(page);
    await mockRoutes.agent(page);
    await mockRoutes.stats(page, { error: "Internal server error", status: 500 });

    // Navigate to agent detail page
    await page.goto("/agents/agent-1");
    await expect(page.getByText("Customer Support Bot")).toBeVisible();

    // Navigate to stats tab
    await page.getByRole("tab", { name: "Stats" }).click();

    // Should show error state
    await expect(page.getByText("Failed to load stats")).toBeVisible();
  });
});
