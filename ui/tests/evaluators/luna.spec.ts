/**
 * Integration tests for the Luna evaluator form
 */

import { expect, test } from '../fixtures';
import { openEvaluatorForm } from './helpers';

test.describe('Luna Evaluator', () => {
  test('displays scorer fields', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'Galileo Luna');

    await expect(
      mockedPage.getByText('Scorer label', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Scorer ID', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Scorer version ID', { exact: true })
    ).toBeVisible();
  });

  test('displays comparison fields', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'Galileo Luna');

    await expect(
      mockedPage.getByText('Operator', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Threshold', { exact: true })
    ).toBeVisible();
  });

  test('displays advanced settings', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'Galileo Luna');

    await expect(
      mockedPage.getByText('Payload field', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Timeout (ms)', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Scorer config', { exact: true })
    ).toBeVisible();
  });

  test('threshold input is enabled by default', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'Galileo Luna');

    const thresholdInput = mockedPage.getByPlaceholder('0.5');
    await expect(thresholdInput).toBeEnabled();
    await expect(thresholdInput).toHaveValue('0.5');
  });
});
