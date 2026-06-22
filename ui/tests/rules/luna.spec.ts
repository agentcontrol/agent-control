/**
 * Integration tests for the Luna rule form
 */

import { expect, test } from '../fixtures';
import { openRuleForm } from './helpers';

test.describe('Luna Rule', () => {
  test('displays scorer fields', async ({ mockedPage }) => {
    await openRuleForm(mockedPage, 'Galileo Luna');

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
    await openRuleForm(mockedPage, 'Galileo Luna');

    await expect(
      mockedPage.getByText('Operator', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Threshold', { exact: true })
    ).toBeVisible();
  });

  test('displays advanced settings', async ({ mockedPage }) => {
    await openRuleForm(mockedPage, 'Galileo Luna');

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
    await openRuleForm(mockedPage, 'Galileo Luna');

    const thresholdInput = mockedPage.getByPlaceholder('0.5');
    await expect(thresholdInput).toBeEnabled();
    await expect(thresholdInput).toHaveValue('0.5');
  });
});
