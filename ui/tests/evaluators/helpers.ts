/**
 * Shared helpers for evaluator tests
 */

import { expect, type Page } from "@playwright/test";

const AGENT_URL = "/agents/9c15431d-c252-4c1b-80e0-d49ecda4f4b5";

/**
 * Opens the control store and selects an evaluator to create a new control
 */
export async function openEvaluatorForm(page: Page, evaluatorName: string) {
  await page.goto(AGENT_URL);

  // Open control store modal (add-new flow)
  await page.getByTestId("add-control-button").first().click();
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
