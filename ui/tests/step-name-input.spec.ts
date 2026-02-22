/**
 * Integration tests for the StepNameInput component (step name / regex mode toggle).
 * The component is exercised within the Create Control modal.
 */

import { openEvaluatorForm } from './evaluators/helpers';
import { expect, test } from './fixtures';

test.describe('Step Name Input', () => {
  test('displays Step name label and Regex toggle', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'Regex');

    const modal = mockedPage.getByRole('dialog', { name: 'Create Control' });
    await expect(modal.getByText('Step name')).toBeVisible();
    await expect(modal.getByText('Regex')).toBeVisible();
  });

  test('defaults to names mode with step selector', async ({
    mockedPage,
  }) => {
    await openEvaluatorForm(mockedPage, 'Regex');

    const modal = mockedPage.getByRole('dialog', { name: 'Create Control' });
    const namesInput = modal.getByPlaceholder('No steps available');
    await expect(namesInput).toBeVisible();
    await expect(modal.getByPlaceholder('^db_.*')).not.toBeVisible();
  });

  test('toggling Regex on shows regex input and hides names input', async ({
    mockedPage,
  }) => {
    await openEvaluatorForm(mockedPage, 'Regex');

    const modal = mockedPage.getByRole('dialog', { name: 'Create Control' });
    await expect(modal.getByPlaceholder('No steps available')).toBeVisible();

    // Click the visible "Regex" label (switch is in ScrollArea and can be out of viewport)
    await modal.getByText('Regex', { exact: true }).click();

    await expect(modal.getByPlaceholder('^db_.*')).toBeVisible();
    await expect(modal.getByPlaceholder('No steps available')).not.toBeVisible();
  });

  test('can type in regex field and value persists when toggling', async ({
    mockedPage,
  }) => {
    await openEvaluatorForm(mockedPage, 'Regex');

    const modal = mockedPage.getByRole('dialog', { name: 'Create Control' });
    await modal.getByText('Regex', { exact: true }).click();

    const regexInput = modal.getByPlaceholder('^db_.*');
    await regexInput.fill('^db_.*');

    await expect(regexInput).toHaveValue('^db_.*');

    // Toggle off to names mode
    await modal.getByText('Regex', { exact: true }).click();
    await expect(modal.getByPlaceholder('No steps available')).toBeVisible();

    // Toggle back to regex mode – value should still be there
    await modal.getByText('Regex', { exact: true }).click();
    await expect(modal.getByPlaceholder('^db_.*')).toHaveValue('^db_.*');
  });

  test('does not render free-text step name input', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'Regex');

    const modal = mockedPage.getByRole('dialog', { name: 'Create Control' });
    await expect(modal.getByPlaceholder('No steps available')).toBeVisible();
    await expect(modal.getByPlaceholder('search_db, fetch_user')).toHaveCount(0);
  });

  test('toggling Regex off shows names input and hides regex input', async ({
    mockedPage,
  }) => {
    await openEvaluatorForm(mockedPage, 'Regex');

    const modal = mockedPage.getByRole('dialog', { name: 'Create Control' });
    await modal.getByText('Regex', { exact: true }).click();
    await expect(modal.getByPlaceholder('^db_.*')).toBeVisible();

    await modal.getByText('Regex', { exact: true }).click();

    await expect(modal.getByPlaceholder('No steps available')).toBeVisible();
    await expect(modal.getByPlaceholder('^db_.*')).not.toBeVisible();
  });
});
