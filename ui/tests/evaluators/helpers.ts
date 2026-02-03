/**
 * Shared helpers for evaluator tests
 */

import { expect, type Page } from "@playwright/test";

const AGENT_URL = "/agents/agent-1/controls";

/**
 * Opens the control store and selects an evaluator to create a new control
 */
export async function openEvaluatorForm(page: Page, evaluatorName: string) {
  await page.goto(AGENT_URL);

  // Open control store modal
  await page.getByTestId("add-control-button").first().click();
  const controlStoreModal = page
    .getByRole("dialog")
    .filter({ hasText: "Browse existing controls or create a new one" });
  await expect(controlStoreModal).toBeVisible();

  // Open the add-new-control modal via footer CTA
  await controlStoreModal.getByTestId("footer-new-control-button").click();
  const addNewModal = page
    .getByRole("dialog")
    .filter({ hasText: "Select an evaluator to create a new control" });
  await expect(addNewModal).toBeVisible();

  // Find and click Add button for the evaluator
  const evaluatorRow = addNewModal.locator("tr", { hasText: evaluatorName });
  await evaluatorRow.getByRole("button", { name: "Use" }).click();

  // Wait for the create control modal (scope to dialog to avoid multiple headings)
  await expect(page.getByRole("dialog", { name: "Create Control" })).toBeVisible();
}

