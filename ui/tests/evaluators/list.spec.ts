/**
 * Integration tests for the List evaluator form
 */

import { expect, test } from '../fixtures';
import { openEvaluatorForm } from './helpers';

test.describe('List Evaluator', () => {
  test('displays all list form fields', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'List');

    // Values textarea (use exact match to avoid matching description)
    await expect(mockedPage.getByText('Values', { exact: true })).toBeVisible();
    await expect(
      mockedPage.getByPlaceholder('Enter values (one per line)')
    ).toBeVisible();

    // Logic select
    await expect(mockedPage.getByText('Logic', { exact: true })).toBeVisible();

    // Match on select
    await expect(
      mockedPage.getByText('Match on', { exact: true })
    ).toBeVisible();

    // Match mode select
    await expect(
      mockedPage.getByText('Match mode', { exact: true })
    ).toBeVisible();

    // Case sensitive checkbox
    await expect(mockedPage.getByText('Case sensitive')).toBeVisible();
  });

  test('can enter multiple values', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'List');

    const valuesTextarea = mockedPage.getByPlaceholder(
      'Enter values (one per line)'
    );
    await valuesTextarea.fill('admin\nroot\nsuper_user');

    await expect(valuesTextarea).toHaveValue('admin\nroot\nsuper_user');
  });

  test('can toggle case sensitive', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'List');

    const checkbox = mockedPage.getByRole('checkbox', {
      name: 'Case sensitive',
    });
    await expect(checkbox).not.toBeChecked();

    await checkbox.click();
    await expect(checkbox).toBeChecked();
  });
});
