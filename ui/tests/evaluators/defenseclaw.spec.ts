/** Integration tests for the DefenseClaw evaluator forms. */

import { expect, test } from '../fixtures';
import { openEvaluatorForm } from './helpers';

test.describe('DefenseClaw Rule Pack Evaluator', () => {
  test('shows typed rule fields and hides wire constants', async ({
    mockedPage,
  }) => {
    await openEvaluatorForm(mockedPage, 'DefenseClaw Rule Pack');

    await expect(
      mockedPage.getByRole('textbox', { name: 'Execution environment' })
    ).toHaveValue('SDK');
    await expect(
      mockedPage.getByRole('textbox', { name: 'Execution environment' })
    ).toBeDisabled();

    await expect(mockedPage.getByLabel('Rule ID')).toBeVisible();
    await expect(mockedPage.getByLabel('Title')).toBeVisible();
    await expect(mockedPage.getByLabel('Pattern')).toBeVisible();
    await expect(
      mockedPage.getByRole('textbox', { name: 'Severity' })
    ).toBeVisible();
    await expect(mockedPage.getByLabel('Confidence')).toBeVisible();
    await expect(
      mockedPage.getByRole('textbox', { name: 'Tags' })
    ).toBeVisible();

    await expect(
      mockedPage.getByText('Schema version', { exact: true })
    ).toHaveCount(0);
    await expect(mockedPage.getByText('Version', { exact: true })).toHaveCount(
      0
    );
    await expect(mockedPage.getByText('Category', { exact: true })).toHaveCount(
      0
    );
  });

  test('can add and remove rules', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'DefenseClaw Rule Pack');

    await mockedPage.getByRole('button', { name: 'Add rule' }).click();
    await expect(mockedPage.getByText('Rule 2', { exact: true })).toBeVisible();

    await mockedPage.getByRole('button', { name: 'Remove rule 2' }).click();
    await expect(mockedPage.getByText('Rule 2', { exact: true })).toHaveCount(
      0
    );
  });
});

test.describe('DefenseClaw OPA Policy Evaluator', () => {
  test('shows policy fields and hides schema version', async ({
    mockedPage,
  }) => {
    await openEvaluatorForm(mockedPage, 'DefenseClaw OPA Policy');

    await expect(
      mockedPage.getByRole('textbox', { name: 'Execution environment' })
    ).toHaveValue('SDK');
    await expect(
      mockedPage.getByRole('textbox', { name: 'Execution environment' })
    ).toBeDisabled();

    await expect(
      mockedPage.getByRole('textbox', { name: 'Domain' })
    ).toBeVisible();
    await expect(
      mockedPage.getByRole('textbox', { name: 'Block at' })
    ).toBeVisible();
    await expect(
      mockedPage.getByRole('textbox', { name: 'Alert at' })
    ).toBeVisible();
    await expect(
      mockedPage.getByRole('textbox', { name: 'Cisco trust level' })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Schema version', { exact: true })
    ).toHaveCount(0);
  });
});
