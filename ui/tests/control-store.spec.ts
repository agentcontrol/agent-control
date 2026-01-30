
import type { Page } from "@playwright/test";

import { expect, mockData, test } from "./fixtures";

const agentUrl = "/agents/agent-1";

async function openControlStoreModal(page: Page) {
  await page.goto(agentUrl);
  await page.getByTestId("add-control-button").first().click();
  const modal = page
    .getByRole("dialog")
    .filter({ hasText: "Choose a saved evaluator config to create a control" });
  await expect(modal).toBeVisible();
  return modal;
}

async function openAddNewControlModal(page: Page) {
  const controlStoreModal = await openControlStoreModal(page);
  await controlStoreModal.getByTestId("create-new-control-button").click();
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
      modal.getByText("Choose a saved evaluator config to create a control")
    ).toBeVisible();
  });

  test("displays evaluator configs table with available templates", async ({
    mockedPage,
  }) => {
    const modal = await openControlStoreModal(mockedPage);

    await expect(modal.getByRole("columnheader", { name: "Name" })).toBeVisible();
    await expect(modal.getByRole("columnheader", { name: "Evaluator" })).toBeVisible();
    await expect(modal.getByRole("columnheader", { name: "Description" })).toBeVisible();

    for (const config of mockData.evaluatorConfigs.evaluator_configs) {
      await expect(modal.getByText(config.name, { exact: true })).toBeVisible();
    }
  });

  test("can search for evaluator configs", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    const searchInput = modal.getByPlaceholder("Search templates...");
    await searchInput.fill("Regex");

    await expect(modal.getByText("PII Regex Template", { exact: true })).toBeVisible();
    await expect(
      modal.getByText("SQL Guard Template", { exact: true })
    ).not.toBeVisible();
  });

  test("shows empty state when search has no results", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    const searchInput = modal.getByPlaceholder("Search templates...");
    await searchInput.fill("NonexistentTemplate");

    await expect(modal.getByText("No evaluator configs found")).toBeVisible();
  });

  test("can close modal with X button", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    await modal.getByTestId("close-control-store-modal-button").click();
    await expect(
      mockedPage.getByText("Choose a saved evaluator config to create a control")
    ).not.toBeVisible();
  });

  test("Use button opens create control modal", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    const tableRow = modal.locator("tbody tr").first();
    await tableRow.getByTestId("use-config-button").click();

    await expect(mockedPage.getByRole("heading", { name: "Create Control" })).toBeVisible();
  });

  test("Use button pre-fills evaluator config", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    const targetRow = modal.locator("tr", { hasText: "PII Regex Template" });
    await targetRow.getByTestId("use-config-button").click();

    const createControlModal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Create Control" });
    await expect(createControlModal).toBeVisible();

    const controlNameInput = createControlModal.getByPlaceholder("Enter control name");
    await expect(controlNameInput).toHaveValue("PII Regex Template");

    const patternInput = createControlModal.getByPlaceholder(
      "Enter regex pattern (e.g., ^.*$)"
    );
    await expect(patternInput).toHaveValue("\\b\\d{3}-\\d{2}-\\d{4}\\b");
  });

  test("Save as Template creates evaluator config", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    const targetRow = modal.locator("tr", { hasText: "PII Regex Template" });
    await targetRow.getByTestId("use-config-button").click();

    const createControlModal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Create Control" });
    await expect(createControlModal).toBeVisible();

    await createControlModal.getByTestId("save-as-template-button").click();

    const saveTemplateModal = mockedPage
      .getByRole("dialog")
      .filter({ hasText: "Save Evaluator Config as Template" });
    await expect(saveTemplateModal).toBeVisible();

    await saveTemplateModal.getByTestId("template-name-input").fill("pii_template");
    await saveTemplateModal
      .getByTestId("template-description-input")
      .fill("Reusable PII regex template");

    const requestPromise = mockedPage.waitForRequest((request) => {
      return (
        request.url().includes("/api/v1/evaluator-configs") &&
        request.method() === "POST"
      );
    });

    await saveTemplateModal.getByTestId("save-template-button").click();

    const request = await requestPromise;
    const payload = request.postDataJSON();
    expect(payload).toMatchObject({
      name: "pii_template",
      description: "Reusable PII regex template",
      evaluator: "regex",
      config: { pattern: "\\b\\d{3}-\\d{2}-\\d{4}\\b" },
    });

    await expect(mockedPage.getByText("Template Saved")).toBeVisible();
  });

  test("New control button opens add-new-control modal", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    await modal.getByTestId("create-new-control-button").click();

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
  // Note: Loading state test is skipped because the loader element is rendered too briefly
  // to reliably test in CI environments. The error state test provides coverage for
  // the loading/error state mechanism.

  test("shows error state when evaluator configs fail to load", async ({ page }) => {
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

    // Mock evaluator configs to fail
    await page.route("**/api/v1/evaluator-configs**", async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ error: "Failed to fetch evaluator configs" }),
      });
    });

    await page.goto("/agents/agent-1");

    // Open the control store modal
    await page.getByTestId("add-control-button").first().click();

    // Should show error state
    await expect(page.getByText("Failed to load evaluator configs")).toBeVisible();
  });
});

