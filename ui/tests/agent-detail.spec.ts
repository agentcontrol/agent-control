import type { AgentControlsResponse, GetAgentResponse } from "@/core/api/types";

import { expect, mockData, test } from "./fixtures";

test.describe("Agent Detail Page", () => {
  const agentId = "agent-1";
  const agentUrl = `/agents/${agentId}`;

  // Type-safe access to mock agent data
  const agentData: GetAgentResponse = mockData.agent;

  test("displays agent header with name and description", async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Check agent name is displayed
    await expect(
      mockedPage.getByRole("heading", { name: agentData.agent.agent_name })
    ).toBeVisible();

    // Check agent description (using non-null assertion since we know mock data has it)
    await expect(mockedPage.getByText(agentData.agent.agent_description!)).toBeVisible();
  });

  test("displays tabs navigation", async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Check all tabs are present
    await expect(mockedPage.getByRole("tab", { name: /Controls/i })).toBeVisible();
    await expect(mockedPage.getByRole("tab", { name: /Stats/i })).toBeVisible();
  });

  test("controls tab is active by default", async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Controls tab should be selected
    const controlsTab = mockedPage.getByRole("tab", { name: /Controls/i });
    await expect(controlsTab).toHaveAttribute("aria-selected", "true");
  });

  test("displays controls table with data", async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Wait for controls to load - scope to the Controls tab panel
    const controlsPanel = mockedPage.getByRole("tabpanel", { name: /Controls/i });
    await expect(controlsPanel.getByRole("table")).toBeVisible();

    // Check control names are displayed in the controls table
    for (const control of mockData.controls.controls) {
      await expect(controlsPanel.getByText(control.name)).toBeVisible();
    }
  });

  test("filters controls when searching", async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Wait for controls to load
    const controlsPanel = mockedPage.getByRole("tabpanel", { name: /Controls/i });
    await expect(controlsPanel.getByRole("table")).toBeVisible();

    // All controls should be visible initially
    await expect(controlsPanel.getByText("PII Detection")).toBeVisible();
    await expect(controlsPanel.getByText("SQL Injection Guard")).toBeVisible();
    await expect(controlsPanel.getByText("Rate Limiter")).toBeVisible();

    // Type in the search box to filter
    const searchInput = mockedPage.getByPlaceholder("Search controls...");
    await searchInput.fill("SQL");

    // Only the matching control should be visible
    await expect(controlsPanel.getByText("SQL Injection Guard")).toBeVisible();

    // Non-matching controls should be hidden
    await expect(controlsPanel.getByText("PII Detection")).not.toBeVisible();
    await expect(controlsPanel.getByText("Rate Limiter")).not.toBeVisible();

    // Clear search to show all controls again
    await searchInput.clear();
    await expect(controlsPanel.getByText("PII Detection")).toBeVisible();
    await expect(controlsPanel.getByText("SQL Injection Guard")).toBeVisible();
    await expect(controlsPanel.getByText("Rate Limiter")).toBeVisible();
  });

  test("displays control badges for step types and stages", async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Wait for controls to load
    await expect(mockedPage.getByRole("table")).toBeVisible();

    // Check that badges are displayed (LLM or Tool) - use first() since multiple rows may have same badge
    await expect(mockedPage.getByText("LLM").first()).toBeVisible();
    await expect(mockedPage.getByText("Tool").first()).toBeVisible();

    // Check stage badges (Pre or Post) - use first() since multiple rows may have same badge
    await expect(mockedPage.getByText("Pre").first()).toBeVisible();
    await expect(mockedPage.getByText("Post").first()).toBeVisible();
  });

  test("shows Add Control button", async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Check Add Control button exists
    await expect(mockedPage.getByTestId("add-control-button").first()).toBeVisible();
  });

  test("opens control store modal when Add Control is clicked", async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Click Add Control button
    await mockedPage.getByTestId("add-control-button").first().click();

    // Control store modal should be visible
    await expect(mockedPage.getByRole("heading", { name: "Control store" })).toBeVisible();
  });

  test("shows loading state while fetching controls", async ({ page }) => {
    let resolveControls: () => void;
    const controlsPromise = new Promise<void>((resolve) => {
      resolveControls = resolve;
    });

    // Mock agent controls - wait for manual trigger
    await page.route("**/api/v1/agents/*/controls", async (route) => {
      await controlsPromise;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockData.controls),
      });
    });

    // Mock single agent (registered after controls route)
    await page.route("**/api/v1/agents/*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockData.agent),
      });
    });

    await page.goto(agentUrl);

    // Check for loading indicator (controls request is blocked, so loading state is guaranteed)
    await expect(page.getByText("Loading controls...")).toBeVisible();

    // Release the controls request
    resolveControls!();

    // Wait for controls to load
    await expect(page.getByRole("table")).toBeVisible();
  });

  test("handles agent not found error", async ({ page }) => {
    // Mock controls to return 404
    await page.route("**/api/v1/agents/*/controls", async (route) => {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ error: "Agent not found" }),
      });
    });

    // Mock agent to return 404
    await page.route("**/api/v1/agents/*", async (route) => {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ error: "Agent not found" }),
      });
    });

    await page.goto(agentUrl);

    // Check for error message
    await expect(page.getByText("Error loading agent")).toBeVisible();
  });

  test("can switch between tabs", async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Click Stats tab
    await mockedPage.getByRole("tab", { name: /Stats/i }).click();
    await expect(
      mockedPage.getByRole("heading", { name: "Control Statistics", exact: true })
    ).toBeVisible();

    // Switch back to Controls
    await mockedPage.getByRole("tab", { name: /Controls/i }).click();
    await expect(mockedPage.getByRole("table")).toBeVisible();
  });

  test("opens edit control modal when edit button is clicked", async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Wait for controls to load
    await expect(mockedPage.getByRole("table")).toBeVisible();

    // Find and click the first edit button in a row
    const rows = mockedPage.locator("tbody tr");
    const firstRow = rows.first();
    const editButton = firstRow.locator('button:has(svg[class*="icon-pencil"])');

    // If that doesn't work, try clicking any action button in the row
    if ((await editButton.count()) === 0) {
      const actionButtons = firstRow.locator("button").last();
      await actionButtons.click();
    } else {
      await editButton.click();
    }

    // Edit modal should be visible
    await expect(mockedPage.getByRole("heading", { name: "Configure Control" })).toBeVisible();
  });

  test("edit control modal pre-fills scope and execution fields", async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Wait for controls to load
    await expect(mockedPage.getByRole("table")).toBeVisible();

    const targetRow = mockedPage.locator("tr", { hasText: "SQL Injection Guard" });
    const editButton = targetRow.locator('button:has(svg[class*="icon-pencil"])');

    if ((await editButton.count()) === 0) {
      await targetRow.locator("button").last().click();
    } else {
      await editButton.click();
    }

    await expect(
      mockedPage.getByRole("heading", { name: "Configure Control" })
    ).toBeVisible();

    const modal = mockedPage.getByRole("dialog");

    await expect(modal.getByText("Step types")).toBeVisible();
    await expect(modal.getByText("Stages")).toBeVisible();
    await expect(modal.getByText("Step names")).toBeVisible();
    await expect(modal.getByText("Step name regex")).toBeVisible();
    await expect(modal.getByText("Execution environment")).toBeVisible();

    await expect(modal.getByText("tool", { exact: true })).toBeVisible();
    await expect(
      modal.getByText("Pre (before execution)", { exact: true })
    ).toBeVisible();
    await expect(modal.getByPlaceholder("search_db, fetch_user")).toHaveValue(
      "database_query"
    );
    await expect(modal.getByPlaceholder("^db_.*")).toHaveValue("^db_.*");
    const executionLabel = modal.getByText("Execution environment", { exact: true });
    await executionLabel.scrollIntoViewIfNeeded();
    await expect(executionLabel).toBeVisible();

    const executionField = executionLabel.locator("..").locator("..");
    const executionInput = executionField.getByRole("textbox");
    await expect(executionInput).toHaveValue("Server");
  });
});

test.describe("Agent Detail - Empty State", () => {
  test("shows empty state when no controls exist", async ({ page }) => {
    // Type-safe empty controls response
    const emptyControlsResponse: AgentControlsResponse = { controls: [] };

    // Mock controls to return empty
    await page.route("**/api/v1/agents/*/controls", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(emptyControlsResponse),
      });
    });

    // Mock agent to return normally
    await page.route("**/api/v1/agents/*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockData.agent),
      });
    });

    await page.goto("/agents/agent-1");

    // Check for empty state message
    await expect(page.getByText("No controls configured")).toBeVisible();
    await expect(page.getByText("This agent doesn't have any controls set up yet.")).toBeVisible();

    // Empty state should have Add Control button (there are 2 - one in header, one in content)
    await expect(page.getByTestId("add-control-button").first()).toBeVisible();
  });
});
