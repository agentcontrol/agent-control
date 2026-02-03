import type { Page } from "@playwright/test";

import { expect, mockData, test } from "./fixtures";

const agentUrl = "/agents/9c15431d-c252-4c1b-80e0-d49ecda4f4b5";

async function openControlStoreModal(page: Page) {
  await page.goto(agentUrl);
  await page.getByTestId("add-control-button").first().click();
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
      modal.getByText("Browse and add controls to your agent")
    ).toBeVisible();
  });

  test("displays source selection sidebar", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    await expect(modal.getByRole("button", { name: "OOB standard" })).toBeVisible();
    await expect(modal.getByRole("button", { name: "Custom" })).toBeVisible();
  });

  test("OOB standard is selected by default", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    await expect(modal.getByText("OOB standard")).toBeVisible();
  });

  test("displays evaluators table with available evaluators", async ({
    mockedPage,
  }) => {
    const modal = await openControlStoreModal(mockedPage);
    await expect(modal.getByRole("columnheader", { name: "Name" })).toBeVisible();
    await expect(modal.getByRole("columnheader", { name: "Version" })).toBeVisible();
    await expect(modal.getByRole("columnheader", { name: "Description" })).toBeVisible();

    const evaluators = Object.values(mockData.evaluators);
    for (const evaluator of evaluators) {
      await expect(modal.getByText(evaluator.name, { exact: true }).first()).toBeVisible();
    }
  });

  test("can search for evaluators", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    const searchInput = modal.getByPlaceholder("Search or apply filter...");
    await searchInput.fill("Regex");

    await expect(modal.getByRole("cell", { name: "Regex" })).toBeVisible();
    await expect(modal.getByRole("cell", { name: "SQL" })).not.toBeVisible();
  });

  test("shows empty state when search has no results", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    const searchInput = modal.getByPlaceholder("Search or apply filter...");
    await searchInput.fill("NonexistentEvaluator");

    await expect(modal.getByText("No evaluators found")).toBeVisible();
  });

  test("shows empty state for Custom source", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    await modal.getByRole("button", { name: "Custom" }).click();

    await expect(modal.getByText("No custom controls yet")).toBeVisible();
    await expect(
      modal.getByText("Create your first custom control to get started")
    ).toBeVisible();
  });

  test("Add button opens create control modal", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    const tableRow = modal.locator("tbody tr").first();
    await tableRow.getByRole("button", { name: "Add" }).click();

    await expect(mockedPage.getByRole("heading", { name: "Create Control" })).toBeVisible();
  });

  test("displays docs link", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    await expect(modal.getByText("Looking to add custom control?")).toBeVisible();
    await expect(modal.getByText("Check our Docs ↗")).toBeVisible();
  });

  test("can close modal with X button", async ({ mockedPage }) => {
    const modal = await openControlStoreModal(mockedPage);
    await modal.getByTestId("close-control-store-modal-button").click();
    await expect(
      mockedPage.getByText("Browse and add controls to your agent")
    ).not.toBeVisible();
  });
});

test.describe("Control Store - Loading States", () => {
  test("shows error state when evaluators fail to load", async ({ page }) => {
    await page.route("**/api/v1/agents/*/controls", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockData.controls),
      });
    });

    await page.route("**/api/v1/agents/*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockData.agent),
      });
    });

    await page.route("**/api/v1/evaluators", async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ error: "Failed to fetch evaluators" }),
      });
    });

    await page.goto("/agents/9c15431d-c252-4c1b-80e0-d49ecda4f4b5");

    await page.getByTestId("add-control-button").first().click();

    await expect(page.getByText("Failed to load evaluators")).toBeVisible();
  });
});
