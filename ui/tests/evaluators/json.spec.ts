/**
 * Integration tests for the JSON evaluator form
 */

import { expect, test } from '../fixtures';
import { openEvaluatorForm } from './helpers';

test.describe('JSON Evaluator', () => {
  test('displays schema validation section', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'JSON');

    // Use exact match for all labels to avoid matching description or helper text
    await expect(
      mockedPage.getByText('Schema Validation', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('JSON Schema', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByPlaceholder('{"type": "object", "properties": {...}}')
    ).toBeVisible();
  });

  test('displays field validation section', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'JSON');

    await expect(
      mockedPage.getByText('Field Validation', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Required fields', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Field types', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Field constraints', { exact: true })
    ).toBeVisible();
    await expect(
      mockedPage.getByText('Field patterns', { exact: true })
    ).toBeVisible();
  });

  test('displays validation behavior checkboxes', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'JSON');

    await expect(
      mockedPage.getByText('Validation Behavior', { exact: true })
    ).toBeVisible();
    await expect(mockedPage.getByText('Allow extra fields')).toBeVisible();
    await expect(
      mockedPage.getByText('Allow null for required fields')
    ).toBeVisible();
    await expect(mockedPage.getByText('Case sensitive enums')).toBeVisible();
  });

  test('displays error handling section', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'JSON');

    await expect(
      mockedPage.getByText('Error Handling', { exact: true })
    ).toBeVisible();
    await expect(mockedPage.getByText('Allow invalid JSON')).toBeVisible();
  });

  test('can enter JSON schema', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'JSON');

    const schemaTextarea = mockedPage.getByPlaceholder(
      '{"type": "object", "properties": {...}}'
    );
    await schemaTextarea.fill('{"type": "object", "required": ["name"]}');
    await expect(schemaTextarea).toHaveValue(
      '{"type": "object", "required": ["name"]}'
    );
  });

  test('can toggle allow extra fields', async ({ mockedPage }) => {
    await openEvaluatorForm(mockedPage, 'JSON');

    const checkbox = mockedPage.getByRole('checkbox', {
      name: 'Allow extra fields',
    });
    await checkbox.click();
  });
});
