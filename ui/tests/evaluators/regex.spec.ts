/**
 * Integration tests for the Regex evaluator form
 */

import { expect, test } from "../fixtures";
import { openEvaluatorForm } from "./helpers";

test.describe("Regex Evaluator", () => {
  test("displays regex form fields", async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, "Regex");

    // Check pattern field is visible (use exact match to avoid matching description)
    await expect(mockedPage.getByText("Pattern", { exact: true })).toBeVisible();
    await expect(
      mockedPage.getByPlaceholder("Enter regex pattern (e.g., ^.*$)")
    ).toBeVisible();
  });

  test("pattern field has default value", async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, "Regex");

    // Default pattern should be ^.*$
    const patternInput = mockedPage.getByPlaceholder(
      "Enter regex pattern (e.g., ^.*$)"
    );
    await expect(patternInput).toHaveValue("^.*$");
  });

  test("can edit pattern field", async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, "Regex");

    const patternInput = mockedPage.getByPlaceholder(
      "Enter regex pattern (e.g., ^.*$)"
    );
    await patternInput.clear();
    await patternInput.fill("\\d{3}-\\d{2}-\\d{4}");

    await expect(patternInput).toHaveValue("\\d{3}-\\d{2}-\\d{4}");
  });
});
