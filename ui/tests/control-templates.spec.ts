import type { Page } from '@playwright/test';

import { getAgentRoute } from '@/core/constants/agent-routes';

import {
  expect,
  getJsonEditorValue,
  mockData,
  mockRoutes,
  setJsonEditorValue,
  test,
} from './fixtures';

/** Set up mocks for template-backed control flows. */
async function setupTemplateMocks(page: Page) {
  await mockRoutes.agent(page, {
    controls: { data: mockData.controlsWithTemplate },
  });
  await page.route('**/api/v1/controls/10/data', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ data: mockData.templateControl.control }),
    });
  });
  await mockRoutes.controlRenderTemplate(page);
  await mockRoutes.controlPatch(page);
}

test.describe('Control Templates', () => {
  const agentId = 'customer-support-bot';
  const controlsUrl = getAgentRoute(agentId, { tab: 'controls' });
  const editTemplateUrl = getAgentRoute(agentId, {
    tab: 'controls',
    query: { modal: 'edit', controlId: '10' },
  });
  const editRawUrl = getAgentRoute(agentId, {
    tab: 'controls',
    query: { modal: 'edit', controlId: '1' },
  });

  // ---------------------------------------------------------------------------
  // Template badge in controls list
  // ---------------------------------------------------------------------------

  test.describe('Template badge in controls list', () => {
    test('displays Template badge for template-backed controls', async ({
      mockedPage,
    }) => {
      // Given: an agent with both raw and template-backed controls
      await setupTemplateMocks(mockedPage);

      // When: navigating to the controls list
      await mockedPage.goto(controlsUrl);

      // Then: the template-backed control row shows a "Template" badge
      const badge = mockedPage
        .locator('table')
        .getByText('Template', { exact: true });
      await expect(badge).toBeVisible();
    });

    test('does not display Template badge for raw controls', async ({
      mockedPage,
    }) => {
      // Given: an agent with only raw controls (default mock data)

      // When: navigating to the controls list
      await mockedPage.goto(controlsUrl);

      // Then: no "Template" badge appears anywhere in the table
      const badges = mockedPage
        .locator('table')
        .getByText('Template', { exact: true });
      await expect(badges).toHaveCount(0);
    });
  });

  // ---------------------------------------------------------------------------
  // Template-backed control editing
  // ---------------------------------------------------------------------------

  test.describe('Template-backed control editing', () => {
    test('opens parameter form when editing template-backed control', async ({
      mockedPage,
    }) => {
      // Given: a template-backed control with regex and step_name parameters
      await setupTemplateMocks(mockedPage);

      // When: opening the edit modal for the template-backed control
      await mockedPage.goto(editTemplateUrl);

      // Then: the parameter form renders with fields from the template definition
      const dialog = mockedPage.getByRole('dialog');
      await expect(dialog.getByText('Regex Pattern')).toBeVisible();
      await expect(dialog.getByText('Step Name')).toBeVisible();

      // And: the managed-by-template info is shown
      await expect(dialog.getByText(/managed by the template/)).toBeVisible();
    });

    test('shows Template badge in the editor header', async ({
      mockedPage,
    }) => {
      // Given: a template-backed control
      await setupTemplateMocks(mockedPage);

      // When: opening the edit modal
      await mockedPage.goto(editTemplateUrl);

      // Then: the Template badge is visible in the dialog header
      const dialog = mockedPage.getByRole('dialog');
      await expect(
        dialog.getByText('Template', { exact: true }).first()
      ).toBeVisible();
    });

    test('shows Parameters and Full JSON mode switcher', async ({
      mockedPage,
    }) => {
      // Given: a template-backed control in edit mode
      await setupTemplateMocks(mockedPage);

      // When: opening the edit modal
      await mockedPage.goto(editTemplateUrl);

      // Then: both mode options are visible in the segmented control
      const dialog = mockedPage.getByRole('dialog');
      await expect(
        dialog.getByText('Parameters', { exact: true })
      ).toBeVisible();
      await expect(
        dialog.locator('label').getByText('Full JSON')
      ).toBeVisible();
    });

    test('can toggle to Full JSON mode and see template JSON', async ({
      mockedPage,
    }) => {
      // Given: the template edit modal is open in Parameters mode
      await setupTemplateMocks(mockedPage);
      await mockedPage.goto(editTemplateUrl);
      const dialog = mockedPage.getByRole('dialog');

      // When: switching to Full JSON mode
      await dialog.locator('label').getByText('Full JSON').click();

      // Then: the JSON editor shows the full TemplateControlInput with template structure
      const jsonEditor = dialog.getByTestId('template-json-textarea');
      await expect(jsonEditor).toBeVisible();
      const jsonContent = await getJsonEditorValue(
        mockedPage,
        'template-json-textarea'
      );
      expect(jsonContent).toContain('"template"');
      expect(jsonContent).toContain('"template_values"');
      expect(jsonContent).toContain('"definition_template"');
    });

    test('can switch from Full JSON back to Parameters', async ({
      mockedPage,
    }) => {
      // Given: the template edit modal is in Full JSON mode
      await setupTemplateMocks(mockedPage);
      await mockedPage.goto(editTemplateUrl);
      const dialog = mockedPage.getByRole('dialog');
      await dialog.locator('label').getByText('Full JSON').click();
      await expect(dialog.getByTestId('template-json-textarea')).toBeVisible();

      // When: switching back to Parameters mode
      await dialog.locator('label').getByText('Parameters').click();

      // Then: the parameter form fields are visible again
      await expect(dialog.getByText('Regex Pattern')).toBeVisible();
      await expect(dialog.getByText('Step Name')).toBeVisible();
    });

    test('shows read-only control summary in left panel', async ({
      mockedPage,
    }) => {
      // Given: a template-backed control with description, action, and template info
      await setupTemplateMocks(mockedPage);

      // When: opening the edit modal
      await mockedPage.goto(editTemplateUrl);

      // Then: the left panel shows rendered control metadata as read-only
      const dialog = mockedPage.getByRole('dialog');
      await expect(
        dialog.getByText('Deny when input matches pattern')
      ).toBeVisible();
      await expect(dialog.getByText('Regex denial template')).toBeVisible();
      await expect(
        dialog.locator('.mantine-Badge-root').getByText('deny')
      ).toBeVisible();
    });

    test('control name field is pre-filled and editable', async ({
      mockedPage,
    }) => {
      // Given: a template-backed control named "Template Regex Guard"
      await setupTemplateMocks(mockedPage);

      // When: opening the edit modal
      await mockedPage.goto(editTemplateUrl);
      const nameInput = mockedPage.getByPlaceholder('Enter control name');

      // Then: the name field is pre-filled with the control name
      await expect(nameInput).toHaveValue('Template Regex Guard');

      // And: the name field is editable
      await nameInput.clear();
      await nameInput.fill('Renamed Guard');
      await expect(nameInput).toHaveValue('Renamed Guard');
    });

    test('preview panel strips template metadata from rendered output', async ({
      mockedPage,
    }) => {
      // Given: a template-backed control in edit mode with the preview panel
      await setupTemplateMocks(mockedPage);
      await mockedPage.goto(editTemplateUrl);
      const dialog = mockedPage.getByRole('dialog');

      // When: expanding the preview panel (it calls the render endpoint
      // which returns template + template_values in the response)
      await dialog.getByText('Preview rendered control').click();

      // Then: wait for the debounced render to complete and populate the preview
      const preview = dialog.locator('textarea[readonly]');
      await expect(preview).toBeVisible();
      await expect(preview).not.toHaveValue('', { timeout: 5000 });
      const previewContent = await preview.inputValue();

      // And: the preview should contain rendered control fields
      expect(previewContent).toContain('"condition"');
      expect(previewContent).toContain('"action"');
      expect(previewContent).toContain('"execution"');

      // And: template authoring metadata should be stripped from the preview
      expect(previewContent).not.toContain('"template"');
      expect(previewContent).not.toContain('"template_values"');
      expect(previewContent).not.toContain('"definition_template"');
    });
  });

  // ---------------------------------------------------------------------------
  // Raw control editing regression
  // ---------------------------------------------------------------------------

  test.describe('Raw control editing regression', () => {
    test('opens standard form editor for raw controls', async ({
      mockedPage,
    }) => {
      // Given: a raw (non-template) control

      // When: opening the edit modal for that control
      await mockedPage.goto(editRawUrl);

      // Then: the standard form fields are shown
      const dialog = mockedPage.getByRole('dialog');
      await expect(dialog.getByText('Selector path')).toBeVisible();
      await expect(dialog.getByText('Description')).toBeVisible();

      // And: template-specific elements are NOT shown
      await expect(dialog.getByText('Template Parameters')).not.toBeVisible();
      await expect(
        dialog.getByText(/managed by the template/)
      ).not.toBeVisible();
    });

    test('raw control edit does not show Parameters toggle', async ({
      mockedPage,
    }) => {
      // Given: a raw (non-template) control

      // When: opening the edit modal
      await mockedPage.goto(editRawUrl);

      // Then: the "Parameters" toggle (template-only) is not visible
      const dialog = mockedPage.getByRole('dialog');
      await expect(
        dialog.getByText('Parameters', { exact: true })
      ).not.toBeVisible();
    });
  });

  // ---------------------------------------------------------------------------
  // Create from JSON flow
  // ---------------------------------------------------------------------------

  test.describe('Create from JSON flow', () => {
    test('From JSON button opens JSON editor in create modal', async ({
      mockedPage,
    }) => {
      // Given: the agent controls page

      // When: navigating Add Control → Create Control → From JSON
      await mockedPage.goto(controlsUrl);
      await mockedPage.getByTestId('add-control-button').click();
      await mockedPage.getByRole('button', { name: 'Create Control' }).click();
      await mockedPage.getByTestId('from-json-button').click();

      // Then: the JSON editor textarea is visible for pasting control or template JSON
      await expect(
        mockedPage.getByTestId('control-json-textarea')
      ).toBeVisible();
    });

    test('switching to Form mode is blocked when JSON contains a template payload', async ({
      mockedPage,
    }) => {
      // Given: the JSON editor is open with a template payload pasted
      await mockedPage.goto(controlsUrl);
      await mockedPage.getByTestId('add-control-button').click();
      await mockedPage.getByRole('button', { name: 'Create Control' }).click();
      await mockedPage.getByTestId('from-json-button').click();

      const jsonEditor = mockedPage.getByTestId('control-json-textarea');
      await expect(jsonEditor).toBeVisible();

      const templateJson = JSON.stringify({
        template: {
          parameters: {
            pattern: { type: 'regex_re2', label: 'Pattern' },
          },
          definition_template: {
            execution: 'server',
            scope: { stages: ['pre'] },
            condition: {
              selector: { path: 'input' },
              evaluator: {
                name: 'regex',
                config: { pattern: { $param: 'pattern' } },
              },
            },
            action: { decision: 'deny' },
          },
        },
        template_values: {},
      });
      await setJsonEditorValue(
        mockedPage,
        'control-json-textarea',
        templateJson
      );

      // When: attempting to switch to Form mode
      await mockedPage.locator('label').getByText('Form').click();

      // Then: an error message is shown explaining templates can't use Form mode
      await expect(
        mockedPage.getByText(
          'Template-backed controls cannot be edited in Form mode'
        )
      ).toBeVisible();

      // And: the JSON editor is still visible (did not switch)
      await expect(jsonEditor).toBeVisible();
    });
  });
});
