/**
 * Integration tests for the StepNameInput component (step name / regex mode toggle).
 * The component is exercised within the Create Control modal.
 */

import { openEvaluatorForm } from './evaluators/helpers';
import { expect, mockData, mockRoutes, test } from './fixtures';

test.describe('Step Name Input', () => {
  test('displays Step name label and Regex toggle', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'Regex');

    const modal = mockedPage.getByRole('dialog', { name: 'Create Control' });
    await expect(modal.getByText('Step name')).toBeVisible();
    await expect(modal.getByText('Regex')).toBeVisible();
  });

  test('defaults to names mode with step selector', async ({ mockedPage }) => {
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
    await expect(
      modal.getByPlaceholder('No steps available')
    ).not.toBeVisible();
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
    await expect(modal.getByPlaceholder('search_db, fetch_user')).toHaveCount(
      0
    );
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

  test('with populated steps: select, deselect, and summary rendering', async ({
    mockedPage,
  }) => {
    await mockedPage.unroute('**/api/v1/agents/*');
    await mockedPage.unroute('**/api/v1/agents/*/controls');
    await mockRoutes.agent(mockedPage, {
      agent: { data: mockData.agentWithSteps },
    });

    await openEvaluatorForm(mockedPage, 'Regex');

    const modal = mockedPage.getByRole('dialog', { name: 'Create Control' });
    const stepSelect = modal.getByTestId('step-name-select');

    // No placeholder when steps exist; overlay shows "All steps" when none selected
    await expect(modal.getByText('All steps')).toBeVisible();

    // Open dropdown and select one step
    await stepSelect.click();
    await mockedPage.getByText('search_db', { exact: true }).click();
    await expect(
      modal.getByRole('paragraph').filter({ hasText: 'search_db' })
    ).toBeVisible();

    // Select another step – summary shows "first +N"
    await stepSelect.click();
    await mockedPage.getByText('fetch_user', { exact: true }).click();
    await expect(modal.getByText('search_db +1')).toBeVisible();

    // Add third step
    await stepSelect.click();
    await mockedPage.getByText('database_query', { exact: true }).click();
    await expect(modal.getByText('search_db +2')).toBeVisible();

    // Deselect by opening dropdown and unchecking each selected option
    await stepSelect.click();
    await mockedPage
      .getByRole('option', { name: 'search_db', selected: true })
      .click();
    await stepSelect.click();
    await mockedPage
      .getByRole('option', { name: 'fetch_user', selected: true })
      .click();
    await stepSelect.click();
    await mockedPage
      .getByRole('option', { name: 'database_query', selected: true })
      .click();
    await expect(modal.getByText('All steps')).toBeVisible();
  });
});
