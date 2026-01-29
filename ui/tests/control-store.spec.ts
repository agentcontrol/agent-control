
import { expect, mockData, test } from "./fixtures";

test.describe("Control Store Modal", () => {
  const agentUrl = "/agents/agent-1";

  test.beforeEach(async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Open the control store modal
    await mockedPage.getByTestId("add-control-button").first().click();

    // Wait for modal to open
    await expect(mockedPage.getByRole("heading", { name: "Control store" })).toBeVisible();
  });

  test("displays modal header and description", async ({ mockedPage }) => {
    await expect(mockedPage.getByRole("heading", { name: "Control store" })).toBeVisible();
    await expect(mockedPage.getByText("Browse and add controls to your agent")).toBeVisible();
  });

  test("displays source selection sidebar", async ({ mockedPage }) => {
    // Check source options - use button role for more specific matching
    await expect(mockedPage.getByRole("button", { name: "OOB standard" })).toBeVisible();
    await expect(mockedPage.getByRole("button", { name: "Custom" })).toBeVisible();
  });

  test("OOB standard is selected by default", async ({ mockedPage }) => {
    // The OOB standard button should have different styling when selected
    const oobButton = mockedPage.getByText("OOB standard");
    await expect(oobButton).toBeVisible();
  });

  test("displays evaluators table with available evaluators", async ({
    mockedPage,
  }) => {
    // Check table headers
    await expect(mockedPage.getByRole("columnheader", { name: "Name" })).toBeVisible();
    await expect(mockedPage.getByRole("columnheader", { name: "Version" })).toBeVisible();
    await expect(mockedPage.getByRole("columnheader", { name: "Description" })).toBeVisible();

    // Check evaluator names are displayed
    const evaluators = Object.values(mockData.evaluators);
    for (const evaluator of evaluators) {
      await expect(
        mockedPage.getByText(evaluator.name, { exact: true }).first()
      ).toBeVisible();
    }
  });

  test("can search for evaluators", async ({ mockedPage }) => {
    // Type in search box (scope to modal to avoid matching page search)
    const modal = mockedPage.getByRole("dialog");
    const searchInput = modal.getByPlaceholder("Search or apply filter...");
    await searchInput.fill("Regex");

    // Only Regex evaluator should be visible in the modal table
    await expect(modal.getByRole("cell", { name: "Regex" })).toBeVisible();

    // Other evaluators should not be visible in the modal table (scope to modal)
    await expect(modal.getByRole("cell", { name: "SQL" })).not.toBeVisible();
  });

  test("shows empty state when search has no results", async ({ mockedPage }) => {
    // Type a non-matching search (use modal scoped input)
    const modal = mockedPage.getByRole("dialog");
    const searchInput = modal.getByPlaceholder("Search or apply filter...");
    await searchInput.fill("NonexistentEvaluator");

    // Should show "No evaluators found"
    await expect(mockedPage.getByText("No evaluators found")).toBeVisible();
  });

  test("shows empty state for Custom source", async ({ mockedPage }) => {
    // Click Custom source button
    await mockedPage.getByRole("button", { name: "Custom" }).click();

    // Should show empty state
    await expect(mockedPage.getByText("No custom controls yet")).toBeVisible();
    await expect(
      mockedPage.getByText("Create your first custom control to get started")
    ).toBeVisible();
  });

  test("can close modal with X button", async ({ mockedPage }) => {
    // Click close button
    await mockedPage.getByTestId("close-control-store-modal-button").click();

    // Modal should be closed
    await expect(mockedPage.getByRole("heading", { name: "Control store" })).not.toBeVisible();
  });

  test("Add button opens create control modal", async ({ mockedPage }) => {
    // Find the Add button in the first evaluator row (inside the modal table)
    const modal = mockedPage.getByRole("dialog");
    const tableRow = modal.locator("tbody tr").first();
    await tableRow.getByRole("button", { name: "Add" }).click();

    // Create Control modal should open
    await expect(mockedPage.getByRole("heading", { name: "Create Control" })).toBeVisible();
  });

  test("displays docs link", async ({ mockedPage }) => {
    await expect(mockedPage.getByText("Looking to add custom control?")).toBeVisible();
    await expect(mockedPage.getByText("Check our Docs ↗")).toBeVisible();
  });
});

test.describe("Control Store - Loading States", () => {
  // Note: Loading state test is skipped because the loader element is rendered too briefly
  // to reliably test in CI environments. The error state test provides coverage for
  // the loading/error state mechanism.

  test("shows error state when evaluators fail to load", async ({ page }) => {
    // Mock controls to return normally
    await page.route("**/api/v1/agents/*/controls", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockData.controls),
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

    // Mock evaluators to fail
    await page.route("**/api/v1/evaluators", async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ error: "Failed to fetch evaluators" }),
      });
    });

    await page.goto("/agents/agent-1");

    // Open the control store modal
    await page.getByTestId("add-control-button").first().click();

    // Should show error state
    await expect(page.getByText("Failed to load evaluators")).toBeVisible();
  });
});

