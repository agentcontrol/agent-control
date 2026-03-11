/**
 * Integration tests for the Luna2 evaluator form
 */

import { expect, test } from '../fixtures';
import { openEvaluatorForm } from './helpers';

test.describe('Luna2 Evaluator', () => {
  test('displays stage type selector', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'Galileo Luna-2');

    await expect(
      mockedPage.getByText('Stage type', { exact: true })
    ).toBeVisible();
  });

  test('shows local stage config by default', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'Galileo Luna-2');

    await expect(
      mockedPage.getByText('Local Stage Configuration', { exact: true })
    ).toBeVisible();
    await expect(mockedPage.getByText('Metric', { exact: true })).toBeVisible();
    await expect(
      mockedPage.getByText('Operator', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Target value', { exact: true })
    ).toBeVisible();
  });

  test('displays available metrics', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'Galileo Luna-2');

    // Click the metric select using its placeholder
    const metricSelect = mockedPage.getByPlaceholder('Select a metric');
    await metricSelect.click();

    // Verify metric options
    await expect(
      mockedPage.getByRole('option', { name: 'Input Toxicity' })
    ).toBeVisible();
    await expect(
      mockedPage.getByRole('option', { name: 'Output Toxicity' })
    ).toBeVisible();
    await expect(
      mockedPage.getByRole('option', { name: 'Prompt Injection' })
    ).toBeVisible();
    await expect(
      mockedPage.getByRole('option', { name: 'PII Detection' })
    ).toBeVisible();
    await expect(
      mockedPage.getByRole('option', { name: 'Hallucination' })
    ).toBeVisible();
  });

  test('displays comparison operators', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'Galileo Luna-2');

    // Click the operator select using its placeholder
    const operatorSelect = mockedPage.getByPlaceholder('Select an operator');
    await operatorSelect.click();
    await operatorSelect.press('ArrowDown');

    // Verify operator options
    await expect(
      mockedPage.getByRole('option', { name: '> (greater than)' })
    ).toBeVisible();
    await expect(
      mockedPage.getByRole('option', { name: '< (less than)' })
    ).toBeVisible();
    await expect(
      mockedPage.getByRole('option', { name: '= (equal)' })
    ).toBeVisible();
  });

  test('displays common settings', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'Galileo Luna-2');

    await expect(
      mockedPage.getByText('Common Settings', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Galileo project', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Payload field', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Timeout (ms)', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('On error', { exact: true })
    ).toBeVisible();
  });
});
