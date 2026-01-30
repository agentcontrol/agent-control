/**
 * Shared helpers for evaluator tests
 */

import { expect, type Page } from "@playwright/test";

const AGENT_URL = "/agents/agent-1";

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
    .filter({ hasText: "Browse and add controls to your agent" });
  await expect(addNewModal).toBeVisible();

  // Find and click Add button for the evaluator
  const evaluatorRow = addNewModal.locator("tr", { hasText: evaluatorName });
  await evaluatorRow.getByRole("button", { name: "Add" }).click();

  // Wait for the create control modal
  await expect(page.getByRole("heading", { name: "Create Control" })).toBeVisible();
}

