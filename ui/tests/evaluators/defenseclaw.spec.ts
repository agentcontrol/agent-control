/** Integration tests for the DefenseClaw evaluator forms. */

import { expect, test } from '../fixtures';
import { openEvaluatorForm } from './helpers';

test.describe('DefenseClaw Rule Pack Evaluator', () => {
  test('shows typed rule fields and hides wire constants', async ({
    mockedPage,
  }) => {
    await openEvaluatorForm(mockedPage, 'DefenseClaw Rule Pack');

    await expect(
      mockedPage.getByText('Rule ID', { exact: true })
    ).toBeVisible();
    await expect(mockedPage.getByText('Title', { exact: true })).toBeVisible();
    await expect(
      mockedPage.getByText('Pattern', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Severity', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Confidence', { exact: true })
    ).toBeVisible();
    await expect(mockedPage.getByText('Tags', { exact: true })).toBeVisible();

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

    await expect(mockedPage.getByText('Domain', { exact: true })).toBeVisible();
    await expect(
      mockedPage.getByText('Block at', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Alert at', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Cisco trust level', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Schema version', { exact: true })
    ).toHaveCount(0);
  });
});
