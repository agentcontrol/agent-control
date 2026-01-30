import type { Page } from "@playwright/test";

import { expect, mockData, test } from "./fixtures";

const agentUrl = "/agents/agent-1";

async function openControlStoreModal(page: Page) {
  await page.goto(agentUrl);
  await page.getByTestId("add-control-button").first().click();
  const modal = page
    .getByRole("dialog")
    .filter({ hasText: "Browse existing controls or create a new one" });
  await expect(modal).toBeVisible();
  return modal;
}

async function openAddNewControlModal(page: Page) {
  const controlStoreModal = await openControlStoreModal(page);
  await controlStoreModal.getByTestId("footer-new-control-button").click();
  const modal = page
    .getByRole("dialog")
    .filter({ hasText: "Browse and add controls to your agent" });
  await expect(modal).toBeVisible();
  return modal;
}

test.describe("Control Store Modal", () => {
  test("displays modal header and description", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    await expect(modal.getByRole("heading", { name: "Control store" })).toBeVisible();
    await expect(
      modal.getByText("Browse existing controls or create a new one")
    ).toBeVisible();
  });

  test("displays controls table with available controls", async ({
    mockedPage,
  }) => {
    const modal = await openControlStoreModal(mockedPage);

    await expect(modal.getByRole("columnheader", { name: "Name" })).toBeVisible();
    await expect(modal.getByRole("columnheader", { name: "Description" })).toBeVisible();
    await expect(modal.getByRole("columnheader", { name: "Enabled" })).toBeVisible();
    await expect(modal.getByRole("columnheader", { name: "Used by" })).toBeVisible();

    for (const control of mockData.listControls.controls) {
      await expect(modal.getByText(control.name, { exact: true })).toBeVisible();
    }
  });

  test("displays agent links in Used by column", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);

    // PII Detection is used by Customer Support Bot
    const agentLink = modal.getByRole("link", { name: "Customer Support Bot" }).first();
    await expect(agentLink).toBeVisible();
    // Link includes query param to filter by control name
    await expect(agentLink).toHaveAttribute("href", "/agents/agent-1?q=PII%20Detection");
  });

  test("can search for controls", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    const searchInput = modal.getByPlaceholder("Search controls...");
    
    // Fill search and wait for debounced API request (300ms debounce)
    const searchPromise = mockedPage.waitForRequest((req) => 
      req.url().includes("/api/v1/controls") && req.url().includes("name=SQL")
    );
    await searchInput.fill("SQL");
    await searchPromise;

    await expect(modal.getByText("SQL Injection Guard", { exact: true })).toBeVisible();
    await expect(
      modal.getByText("PII Detection", { exact: true })
    ).not.toBeVisible();
  });

  test("shows empty state when search has no results", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    const searchInput = modal.getByPlaceholder("Search controls...");
    
    // Fill search and wait for debounced API request
    const searchPromise = mockedPage.waitForRequest((req) => 
      req.url().includes("/api/v1/controls") && req.url().includes("name=NonexistentControl")
    );
    await searchInput.fill("NonexistentControl");
    await searchPromise;

    await expect(modal.getByText("No controls found")).toBeVisible();
  });

  test("can close modal with X button", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    await modal.getByTestId("close-control-store-modal-button").click();
    await expect(
      mockedPage.getByText("Browse existing controls or create a new one")
    ).not.toBeVisible();
  });

  test("Use button opens create control modal", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    const tableRow = modal.locator("tbody tr").first();
    await tableRow.getByTestId("use-control-button").click();

    await expect(mockedPage.getByRole("heading", { name: "Create Control" })).toBeVisible();
  });

  test("Use button pre-fills control name and evaluator config", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    const targetRow = modal.locator("tr", { hasText: "PII Detection" });
    await targetRow.getByTestId("use-control-button").click();

    const createControlModal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Create Control" });
    await expect(createControlModal).toBeVisible();

    // Check control name is pre-filled with -copy suffix (sanitized)
    const controlNameInput = createControlModal.getByPlaceholder("Enter control name");
    await expect(controlNameInput).toHaveValue("PII-Detection-copy");

    // Check evaluator config is pre-filled (PII Detection uses regex with SSN pattern)
    const patternInput = createControlModal.getByPlaceholder("Enter regex pattern (e.g., ^.*$)");
    await expect(patternInput).toHaveValue("\\b\\d{3}-\\d{2}-\\d{4}\\b");
  });

  test("Footer 'Create new control' button opens add-new-control modal", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    await modal.getByTestId("footer-new-control-button").click();

    await expect(
      mockedPage.getByText("Browse and add controls to your agent")
    ).toBeVisible();
  });
});

test.describe("Add New Control Modal", () => {
  test("displays modal header and description", async ({ mockedPage }) => {
    const modal = await openAddNewControlModal(mockedPage);
    await expect(modal.getByRole("heading", { name: "Control store" })).toBeVisible();
    await expect(modal.getByText("Browse and add controls to your agent")).toBeVisible();
  });

  test("displays source selection sidebar", async ({ mockedPage }) => {
    const modal = await openAddNewControlModal(mockedPage);
    await expect(modal.getByRole("button", { name: "OOB standard" })).toBeVisible();
    await expect(modal.getByRole("button", { name: "Custom" })).toBeVisible();
  });

  test("OOB standard is selected by default", async ({ mockedPage }) => {
    const modal = await openAddNewControlModal(mockedPage);
    await expect(modal.getByText("OOB standard")).toBeVisible();
  });

  test("displays evaluators table with available evaluators", async ({
    mockedPage,
  }) => {
    const modal = await openAddNewControlModal(mockedPage);
    await expect(modal.getByRole("columnheader", { name: "Name" })).toBeVisible();
    await expect(modal.getByRole("columnheader", { name: "Version" })).toBeVisible();
    await expect(modal.getByRole("columnheader", { name: "Description" })).toBeVisible();

    const evaluators = Object.values(mockData.evaluators);
    for (const evaluator of evaluators) {
      await expect(modal.getByText(evaluator.name, { exact: true }).first()).toBeVisible();
    }
  });

  test("can search for evaluators", async ({ mockedPage }) => {
    const modal = await openAddNewControlModal(mockedPage);
    const searchInput = modal.getByPlaceholder("Search or apply filter...");
    await searchInput.fill("Regex");

    await expect(modal.getByRole("cell", { name: "Regex" })).toBeVisible();
    await expect(modal.getByRole("cell", { name: "SQL" })).not.toBeVisible();
  });

  test("shows empty state when search has no results", async ({ mockedPage }) => {
    const modal = await openAddNewControlModal(mockedPage);
    const searchInput = modal.getByPlaceholder("Search or apply filter...");
    await searchInput.fill("NonexistentEvaluator");

    await expect(modal.getByText("No evaluators found")).toBeVisible();
  });

  test("shows empty state for Custom source", async ({ mockedPage }) => {
    const modal = await openAddNewControlModal(mockedPage);
    await modal.getByRole("button", { name: "Custom" }).click();

    await expect(modal.getByText("No custom controls yet")).toBeVisible();
    await expect(
      modal.getByText("Create your first custom control to get started")
    ).toBeVisible();
  });

  test("Add button opens create control modal", async ({ mockedPage }) => {
    const modal = await openAddNewControlModal(mockedPage);
    const tableRow = modal.locator("tbody tr").first();
    await tableRow.getByRole("button", { name: "Add" }).click();

    await expect(mockedPage.getByRole("heading", { name: "Create Control" })).toBeVisible();
  });

  test("displays docs link", async ({ mockedPage }) => {
    const modal = await openAddNewControlModal(mockedPage);
    await expect(modal.getByText("Looking to add custom control?")).toBeVisible();
    await expect(modal.getByText("Check our Docs ↗")).toBeVisible();
  });
});

test.describe("Control Store - Loading States", () => {
  test("shows error state when controls fail to load", async ({ page }) => {
    // Mock agent controls to return normally
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

    // Mock controls list to fail
    await page.route("**/api/v1/controls**", async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ error: "Failed to fetch controls" }),
      });
    });

    await page.goto("/agents/agent-1");

    // Open the control store modal
    await page.getByTestId("add-control-button").first().click();

    // Should show error state
    await expect(page.getByText("Failed to load controls")).toBeVisible();
  });
});
