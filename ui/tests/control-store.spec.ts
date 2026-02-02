import type { Page } from "@playwright/test";

import { expect, mockData, test } from "./fixtures";

const agentUrl = "/agents/agent-1/controls";

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
    .filter({ hasText: "Select an evaluator to create a new control" });
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
    // Status dot column has no header text, so we skip checking for it
    await expect(modal.getByRole("columnheader", { name: "Agent" })).toBeVisible();

    for (const control of mockData.listControls.controls) {
      await expect(modal.getByText(control.name, { exact: true })).toBeVisible();
    }
  });

  test("displays agent links in Agent column", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);

    // PII Detection is used by Customer Support Bot
    const agentLink = modal.getByRole("link", { name: "Customer Support Bot" }).first();
    await expect(agentLink).toBeVisible();
    // Link includes query param to filter by control name
    await expect(agentLink).toHaveAttribute("href", "/agents/agent-1/controls?q=PII%20Detection");
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

  test("Copy button opens create control modal", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    const tableRow = modal.locator("tbody tr").first();
    await tableRow.getByTestId("copy-control-button").click();

    await expect(mockedPage.getByRole("dialog", { name: "Create Control" })).toBeVisible();
  });

  test("Copy button pre-fills control name and evaluator config", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    const targetRow = modal.locator("tr", { hasText: "PII Detection" });
    await targetRow.getByTestId("copy-control-button").click();

    const createControlModal = mockedPage.getByRole("dialog", {
      name: "Create Control",
    });
    await expect(createControlModal).toBeVisible();

    // Check control name is pre-filled with -copy appended (sanitized)
    const controlNameInput = createControlModal.getByPlaceholder("Enter control name");
    await expect(controlNameInput).toHaveValue("PII-Detection-copy");

    // Check evaluator config is pre-filled (PII Detection uses regex with SSN pattern)
    const patternInput = createControlModal.getByPlaceholder("Enter regex pattern (e.g., ^.*$)");
    await expect(patternInput).toHaveValue("\\b\\d{3}-\\d{2}-\\d{4}\\b");
  });

  test("Create Control button opens add-new-control modal", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    await modal.getByTestId("footer-new-control-button").click();

    await expect(
      mockedPage.getByText("Select an evaluator to create a new control")
    ).toBeVisible();
  });
});

test.describe("Add New Control Modal", () => {
  test("displays modal header and description", async ({ mockedPage }) => {
    const modal = await openAddNewControlModal(mockedPage);
    await expect(modal.getByRole("heading", { name: "Create Control" })).toBeVisible();
    await expect(modal.getByText("Select an evaluator to create a new control")).toBeVisible();
  });

  test("displays evaluators table with available evaluators", async ({
    mockedPage,
  }) => {
    const modal = await openAddNewControlModal(mockedPage);
    await expect(modal.getByRole("columnheader", { name: "Name" })).toBeVisible();
    await expect(modal.getByRole("columnheader", { name: "Description" })).toBeVisible();

    const evaluators = Object.values(mockData.evaluators);
    for (const evaluator of evaluators) {
      await expect(modal.getByText(evaluator.name, { exact: true }).first()).toBeVisible();
    }
  });

  test("can search for evaluators", async ({ mockedPage }) => {
    const modal = await openAddNewControlModal(mockedPage);
    const searchInput = modal.getByPlaceholder("Search evaluators...");
    await searchInput.fill("Regex");

    await expect(modal.getByRole("cell", { name: "Regex" })).toBeVisible();
    await expect(modal.getByRole("cell", { name: "SQL" })).not.toBeVisible();
  });

  test("shows empty state when search has no results", async ({ mockedPage }) => {
    const modal = await openAddNewControlModal(mockedPage);
    const searchInput = modal.getByPlaceholder("Search evaluators...");
    await searchInput.fill("NonexistentEvaluator");

    await expect(modal.getByText("No evaluators found")).toBeVisible();
  });

  test("Use button opens create control modal", async ({ mockedPage }) => {
    const modal = await openAddNewControlModal(mockedPage);
    const tableRow = modal.locator("tbody tr").first();
    await tableRow.getByRole("button", { name: "Use" }).click();

    await expect(mockedPage.getByRole("dialog", { name: "Create Control" })).toBeVisible();
  });

  test("displays docs link", async ({ mockedPage }) => {
    const modal = await openAddNewControlModal(mockedPage);
    await expect(modal.getByText("Learn here on how to add new type of evaluator.")).toBeVisible();
    await expect(modal.getByText("Docs ↗")).toBeVisible();
  });
});

test.describe("Modal Routing", () => {
  test("opens control store modal via URL query parameter", async ({ mockedPage }) => {
    await mockedPage.goto(`${agentUrl}?modal=control-store`);
    
    const modal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Browse existing controls or create a new one" });
    await expect(modal).toBeVisible();
    
    // URL should contain modal parameter
    await expect(mockedPage).toHaveURL(/.*\?modal=control-store/);
  });

  test("opens add-new-control modal via URL query parameters", async ({ mockedPage }) => {
    await mockedPage.goto(`${agentUrl}?modal=control-store&submodal=add-new`);
    
    // Both modals should be visible
    const controlStoreModal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Browse existing controls or create a new one" });
    await expect(controlStoreModal).toBeVisible();
    
    const addNewModal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Select an evaluator to create a new control" });
    await expect(addNewModal).toBeVisible();
    
    // URL should contain both parameters
    await expect(mockedPage).toHaveURL(/.*\?modal=control-store&submodal=add-new/);
  });

  test("opens create control modal via URL query parameters", async ({ mockedPage }) => {
    await mockedPage.goto(`${agentUrl}?modal=control-store&submodal=create&evaluator=list`);
    
    // Control store and add-new modals should be visible (create is nested inside add-new)
    const controlStoreModal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Browse existing controls or create a new one" });
    await expect(controlStoreModal).toBeVisible();
    
    const addNewModal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Select an evaluator to create a new control" });
    await expect(addNewModal).toBeVisible();
    
    // Create control modal should be visible
    const createModal = mockedPage.getByRole("dialog", { name: "Create Control" });
    await expect(createModal).toBeVisible();
    
    // URL should contain all parameters
    await expect(mockedPage).toHaveURL(/.*\?modal=control-store&submodal=create&evaluator=list/);
  });

  test("opens edit control modal via URL query parameters (Copy flow)", async ({ mockedPage }) => {
    // First, we need to get a control ID from the list
    await mockedPage.goto(`${agentUrl}?modal=control-store`);
    const modal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Browse existing controls or create a new one" });
    await expect(modal).toBeVisible();
    
    // Get the first control's ID (we'll use PII Detection which has ID 1 in mock data)
    const targetRow = modal.locator("tr", { hasText: "PII Detection" });
    await targetRow.getByTestId("copy-control-button").click();
    
    // Wait for the edit modal to open
    const editModal = mockedPage.getByRole("dialog", { name: "Create Control" });
    await expect(editModal).toBeVisible();
    
    // URL should contain edit submodal and controlId
    await expect(mockedPage).toHaveURL(/.*\?modal=control-store&submodal=edit&controlId=\d+/);
  });

  test("closing create modal returns to add-new modal", async ({ mockedPage }) => {
    await mockedPage.goto(`${agentUrl}?modal=control-store&submodal=create&evaluator=list`);
    
    // Verify create modal is open
    const createModal = mockedPage.getByRole("dialog", { name: "Create Control" });
    await expect(createModal).toBeVisible();
    
    // Close the create modal (press Escape or click close)
    await mockedPage.keyboard.press("Escape");
    
    // Wait for create modal to close
    await expect(createModal).not.toBeVisible();
    
    // Add-new modal should still be visible
    const addNewModal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Select an evaluator to create a new control" });
    await expect(addNewModal).toBeVisible();
    
    // URL should be back to add-new
    await expect(mockedPage).toHaveURL(/.*\?modal=control-store&submodal=add-new/);
  });

  test("closing edit modal (Copy flow) closes completely", async ({ mockedPage }) => {
    // Open control store and click Copy
    await mockedPage.goto(`${agentUrl}?modal=control-store`);
    const modal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Browse existing controls or create a new one" });
    await expect(modal).toBeVisible();
    
    const targetRow = modal.locator("tr", { hasText: "PII Detection" });
    await targetRow.getByTestId("copy-control-button").click();
    
    // Wait for edit modal to open
    const editModal = mockedPage.getByRole("dialog", { name: "Create Control" });
    await expect(editModal).toBeVisible();
    
    // Close the edit modal (press Escape)
    await mockedPage.keyboard.press("Escape");
    
    // Wait for edit modal to close
    await expect(editModal).not.toBeVisible();
    
    // Control store modal should still be visible
    await expect(modal).toBeVisible();
    
    // URL should only have modal parameter (no submodal)
    await expect(mockedPage).toHaveURL(/.*\?modal=control-store(?!.*submodal)/);
  });

  test("modal state persists on page refresh", async ({ mockedPage }) => {
    // Open modals via URL
    await mockedPage.goto(`${agentUrl}?modal=control-store&submodal=add-new`);
    
    // Verify modals are open
    const controlStoreModal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Browse existing controls or create a new one" });
    await expect(controlStoreModal).toBeVisible();
    
    const addNewModal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Select an evaluator to create a new control" });
    await expect(addNewModal).toBeVisible();
    
    // Refresh the page
    await mockedPage.reload();
    
    // Modals should still be open after refresh
    await expect(controlStoreModal).toBeVisible();
    await expect(addNewModal).toBeVisible();
    
    // URL should still have the parameters
    await expect(mockedPage).toHaveURL(/.*\?modal=control-store&submodal=add-new/);
  });

  test("navigating through modal flow updates URL correctly", async ({ mockedPage }) => {
    // Start at control store
    await mockedPage.goto(`${agentUrl}?modal=control-store`);
    await expect(mockedPage).toHaveURL(/.*\?modal=control-store(?!.*submodal)/);
    
    // Click "Create Control" button
    const controlStoreModal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Browse existing controls or create a new one" });
    await controlStoreModal.getByTestId("footer-new-control-button").click();
    
    // URL should update to include submodal=add-new
    await expect(mockedPage).toHaveURL(/.*\?modal=control-store&submodal=add-new/);
    
    // Click "Use" on an evaluator
    const addNewModal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Select an evaluator to create a new control" });
    const tableRow = addNewModal.locator("tbody tr").first();
    await tableRow.getByRole("button", { name: "Use" }).click();
    
    // URL should update to include submodal=create and evaluator
    await expect(mockedPage).toHaveURL(/.*\?modal=control-store&submodal=create&evaluator=\w+/);
    
    // Create modal should be visible
    const createModal = mockedPage.getByRole("dialog", { name: "Create Control" });
    await expect(createModal).toBeVisible();
  });

  test("closes all modals when control is successfully created", async ({ mockedPage }) => {
    // Navigate to create modal via URL (simulating the full flow)
    await mockedPage.goto(`${agentUrl}?modal=control-store&submodal=create&evaluator=list`);
    
    // Verify all modals are open
    const controlStoreModal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Browse existing controls or create a new one" });
    await expect(controlStoreModal).toBeVisible();
    
    const addNewModal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Select an evaluator to create a new control" });
    await expect(addNewModal).toBeVisible();
    
    const createModal = mockedPage.getByRole("dialog", { name: "Create Control" });
    await expect(createModal).toBeVisible();
    
    // Mock successful API response for control creation
    // Agent already has a policy (return 200 with policy_id)
    await mockedPage.route("**/api/v1/agents/*/policy", async (route, request) => {
      if (request.method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ policy_id: 1 }),
        });
      } else if (request.method() === "POST") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({}),
        });
      } else {
        await route.continue();
      }
    });
    
    await mockedPage.route("**/api/v1/controls", async (route, request) => {
      if (request.method() === "PUT") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ control_id: 100 }),
        });
      } else {
        await route.continue();
      }
    });
    
    await mockedPage.route("**/api/v1/controls/*/data", async (route, request) => {
      if (request.method() === "PUT") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({}),
        });
      } else {
        await route.continue();
      }
    });
    
    await mockedPage.route("**/api/v1/policies/*/controls/*", async (route, request) => {
      if (request.method() === "POST") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({}),
        });
      } else {
        await route.continue();
      }
    });
    
    // Fill out the form and submit
    const controlNameInput = createModal.getByPlaceholder("Enter control name");
    await controlNameInput.fill("Test Control");
    
    // Fill in the required "Values" field for the list evaluator (at least one value required)
    const valuesTextarea = createModal.getByPlaceholder("Enter values (one per line)");
    await valuesTextarea.fill("test-value");
    
    // Submit the form
    const saveButton = createModal.getByRole("button", { name: /Save|Create/i });
    await saveButton.click();
    
    // Wait for confirmation modal to appear
    await mockedPage.waitForTimeout(300); // Wait for modal animation
    
    // Find the confirm button by text - use locator to find button containing "Confirm"
    const confirmButton = mockedPage.locator("button:has-text('Confirm')");
    await expect(confirmButton).toBeVisible({ timeout: 5000 });
    
    // Start waiting for API response before clicking (must be set up before the action)
    const responsePromise = mockedPage.waitForResponse("**/api/v1/policies/*/controls/*", { timeout: 10000 });
    await confirmButton.click();
    
    // Wait for API call to complete
    await responsePromise;
    
    // Wait for all modals to close
    await expect(controlStoreModal).not.toBeVisible({ timeout: 5000 });
    await expect(addNewModal).not.toBeVisible();
    await expect(createModal).not.toBeVisible();
    
    // URL should not contain any modal parameters
    await expect(mockedPage).not.toHaveURL(/.*\?modal=/);
  });

  test("closes all modals when control is successfully copied", async ({ mockedPage }) => {
    // Open control store and click Copy
    await mockedPage.goto(`${agentUrl}?modal=control-store`);
    const controlStoreModal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Browse existing controls or create a new one" });
    await expect(controlStoreModal).toBeVisible();
    
    const targetRow = controlStoreModal.locator("tr", { hasText: "PII Detection" });
    await targetRow.getByTestId("copy-control-button").click();
    
    // Wait for edit modal to open
    const editModal = mockedPage.getByRole("dialog", { name: "Create Control" });
    await expect(editModal).toBeVisible();
    
    // Wait for form to be initialized with control data (control name should contain "-copy")
    const controlNameInput = editModal.getByPlaceholder("Enter control name");
    await expect(controlNameInput).toHaveValue(/.*-copy$/, { timeout: 5000 });
    
    // Set up mock routes for control creation flow (copying creates a new control)
    await mockedPage.route("**/api/v1/agents/*/policy", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ policy_id: 1 }),
      });
    });
    
    await mockedPage.route("**/api/v1/controls", async (route, request) => {
      if (request.method() === "PUT") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ control_id: 100 }),
        });
      } else {
        await route.continue();
      }
    });
    
    await mockedPage.route("**/api/v1/controls/*/data", async (route, request) => {
      if (request.method() === "PUT") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({}),
        });
      } else {
        await route.continue();
      }
    });
    
    await mockedPage.route("**/api/v1/policies/*/controls/*", async (route, request) => {
      if (request.method() === "POST") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({}),
        });
      } else {
        await route.continue();
      }
    });
    
    // Submit the form
    const saveButton = editModal.getByRole("button", { name: /Save|Create/i });
    await saveButton.click();
    
    // Wait for confirmation modal to appear
    await mockedPage.waitForTimeout(300); // Wait for modal animation
    
    // Find the confirm button
    const confirmButton = mockedPage.locator("button:has-text('Confirm')");
    await expect(confirmButton).toBeVisible({ timeout: 5000 });
    
    // Start waiting for API response before clicking (must be set up before the action)
    const responsePromise = mockedPage.waitForResponse("**/api/v1/policies/*/controls/*", { timeout: 10000 });
    await confirmButton.click();
    
    // Wait for API call to complete
    await responsePromise;
    
    // Wait for all modals to close
    await expect(controlStoreModal).not.toBeVisible({ timeout: 5000 });
    await expect(editModal).not.toBeVisible();
    
    // URL should not contain any modal parameters
    await expect(mockedPage).not.toHaveURL(/.*\?modal=/);
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

    await page.goto("/agents/agent-1/controls");

    // Open the control store modal
    await page.getByTestId("add-control-button").first().click();

    // Should show error state
    await expect(page.getByText("Failed to load controls")).toBeVisible();
  });
});
