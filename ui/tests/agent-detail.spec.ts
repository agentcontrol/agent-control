import type {
  AgentControlsResponse,
  Control,
  GetAgentResponse,
} from '@/core/api/types';
import { getAgentRoute } from '@/core/constants/agent-routes';

import {
  expect,
  focusJsonEditorAt,
  getJsonEditorValue,
  getJsonEditorSuggestions,
  mockData,
  mockRoutes,
  setJsonEditorValue,
  test,
} from './fixtures';

test.describe('Agent Detail Page', () => {
  const agentId = 'agent-1';
  const getAgentControlsUrl = (
    query?: Record<string, string | number | boolean>
  ) => getAgentRoute(agentId, { tab: 'controls', query });
  const agentUrl = getAgentControlsUrl();
  const agentMonitorUrl = getAgentRoute(agentId, { tab: 'monitor' });

  // Type-safe access to mock agent data
  const agentData: GetAgentResponse = mockData.agent;

  test('displays agent header with name and description', async ({
    mockedPage,
  }) => {
    await mockedPage.goto(agentUrl);

    // Check agent name is displayed
    await expect(
      mockedPage.getByRole('heading', { name: agentData.agent.agent_name })
    ).toBeVisible();

    // Check agent description (using non-null assertion since we know mock data has it)
    await expect(
      mockedPage.getByText(agentData.agent.agent_description!)
    ).toBeVisible();
  });

  test('displays tabs navigation', async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Check all tabs are present
    await expect(
      mockedPage.getByRole('tab', { name: /Controls/i })
    ).toBeVisible();
    await expect(
      mockedPage.getByRole('tab', { name: /Monitor/i })
    ).toBeVisible();
  });

  test('controls tab is active by default when no stats data', async ({
    mockedPage,
  }) => {
    // Set up mocks with empty stats to ensure Controls tab is shown
    await mockRoutes.agents(mockedPage);
    await mockRoutes.agent(mockedPage);
    await mockRoutes.stats(mockedPage, { data: mockData.emptyStats });

    await mockedPage.goto(agentUrl);

    // Controls tab should be selected when no stats data exists
    const controlsTab = mockedPage.getByRole('tab', { name: /Controls/i });
    await expect(controlsTab).toHaveAttribute('aria-selected', 'true');

    // Monitor tab should not be selected
    const monitorTab = mockedPage.getByRole('tab', { name: /Monitor/i });
    await expect(monitorTab).toHaveAttribute('aria-selected', 'false');
  });

  test('monitor tab is active by default when stats data exists', async ({
    mockedPage,
  }) => {
    // Set up mocks with stats data to ensure Monitor tab is shown
    await mockRoutes.agents(mockedPage);
    await mockRoutes.agent(mockedPage);
    await mockRoutes.stats(mockedPage, { data: mockData.stats });

    await mockedPage.goto(agentMonitorUrl);

    // Wait for stats to load and tab to be set
    await mockedPage.waitForTimeout(100);

    // Monitor tab should be selected when stats data exists
    const monitorTab = mockedPage.getByRole('tab', { name: /Monitor/i });
    await expect(monitorTab).toHaveAttribute('aria-selected', 'true');

    // Controls tab should not be selected
    const controlsTab = mockedPage.getByRole('tab', { name: /Controls/i });
    await expect(controlsTab).toHaveAttribute('aria-selected', 'false');
  });

  test('displays controls table with data', async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Click Controls tab (monitor might be shown by default if stats exist)
    await mockedPage.getByRole('tab', { name: 'Controls' }).click();

    // Wait for controls to load - scope to the Controls tab panel
    const controlsPanel = mockedPage.getByRole('tabpanel', {
      name: /Controls/i,
    });
    await expect(controlsPanel.getByRole('table')).toBeVisible();

    // Check control names are displayed in the controls table
    for (const control of mockData.controls.controls) {
      await expect(controlsPanel.getByText(control.name)).toBeVisible();
    }
  });

  test('filters controls when searching', async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Click Controls tab (monitor might be shown by default if stats exist)
    await mockedPage.getByRole('tab', { name: 'Controls' }).click();

    // Wait for controls to load
    const controlsPanel = mockedPage.getByRole('tabpanel', {
      name: /Controls/i,
    });
    await expect(controlsPanel.getByRole('table')).toBeVisible();

    // All controls should be visible initially
    await expect(controlsPanel.getByText('PII Detection')).toBeVisible();
    await expect(controlsPanel.getByText('SQL Injection Guard')).toBeVisible();
    await expect(controlsPanel.getByText('Rate Limiter')).toBeVisible();

    // Type in the search box to filter
    const searchInput = mockedPage.getByPlaceholder('Search controls...');
    await searchInput.fill('SQL');

    // Only the matching control should be visible
    await expect(controlsPanel.getByText('SQL Injection Guard')).toBeVisible();

    // Non-matching controls should be hidden
    await expect(controlsPanel.getByText('PII Detection')).not.toBeVisible();
    await expect(controlsPanel.getByText('Rate Limiter')).not.toBeVisible();

    // Clear search to show all controls again
    await searchInput.clear();
    await expect(controlsPanel.getByText('PII Detection')).toBeVisible();
    await expect(controlsPanel.getByText('SQL Injection Guard')).toBeVisible();
    await expect(controlsPanel.getByText('Rate Limiter')).toBeVisible();
  });

  test('displays control badges for step types and stages', async ({
    mockedPage,
  }) => {
    await mockedPage.goto(agentUrl);

    // Click Controls tab (monitor might be shown by default if stats exist)
    await mockedPage.getByRole('tab', { name: 'Controls' }).click();

    // Wait for controls to load
    const controlsPanel = mockedPage.getByRole('tabpanel', {
      name: /Controls/i,
    });
    await expect(controlsPanel.getByRole('table')).toBeVisible();

    // Check that badges are displayed (LLM or Tool) - scope to controls panel
    await expect(controlsPanel.getByText('LLM').first()).toBeVisible();
    await expect(controlsPanel.getByText('Tool').first()).toBeVisible();

    // Check stage badges (Pre or Post) - scope to controls panel
    await expect(controlsPanel.getByText('Pre').first()).toBeVisible();
    await expect(controlsPanel.getByText('Post').first()).toBeVisible();
  });

  test('shows Add Control button', async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Check Add Control button exists
    await expect(
      mockedPage.getByTestId('add-control-button').first()
    ).toBeVisible();
  });

  test('opens control store modal when Add Control is clicked', async ({
    mockedPage,
  }) => {
    await mockedPage.goto(agentUrl);

    // Click Add Control button
    await mockedPage.getByTestId('add-control-button').first().click();

    // Control store modal should be visible
    await expect(
      mockedPage.getByRole('heading', { name: 'Control store' })
    ).toBeVisible();

    // URL should contain modal parameter
    await expect(mockedPage).toHaveURL(
      getAgentControlsUrl({ modal: 'control-store' })
    );
  });

  test('closing edit modal removes query parameters', async ({
    mockedPage,
  }) => {
    // Mock empty stats to ensure controls tab is shown
    await mockRoutes.stats(mockedPage, { data: mockData.emptyStats });

    // Open edit modal via URL
    await mockedPage.goto(
      getAgentRoute(agentId, {
        tab: 'controls',
        query: { modal: 'edit', controlId: '1' },
      })
    );

    const editModal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(editModal).toBeVisible();

    // Close the modal via the Cancel button
    await editModal.getByRole('button', { name: 'Cancel' }).click();

    // Modal should be closed
    await expect(editModal).not.toBeVisible();

    // URL should not contain modal parameters
    await expect(mockedPage).not.toHaveURL(/.*\?modal=/);
  });

  test('closes edit modal when control is successfully updated', async ({
    mockedPage,
  }) => {
    // Mock empty stats to ensure controls tab is shown
    await mockRoutes.stats(mockedPage, { data: mockData.emptyStats });

    // Open edit modal via URL
    await mockedPage.goto(
      getAgentRoute(agentId, {
        tab: 'controls',
        query: { modal: 'edit', controlId: '1' },
      })
    );

    const editModal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(editModal).toBeVisible();

    // Mock successful API response for control update
    await mockedPage.route(
      '**/api/v1/controls/*/data',
      async (route, request) => {
        if (request.method() === 'PUT') {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({}),
          });
        } else {
          await route.continue();
        }
      }
    );

    // Submit the form
    const saveButton = editModal.getByRole('button', { name: /Save/i });
    await saveButton.click();

    // Wait for confirmation modal and confirm
    await mockedPage.waitForTimeout(300); // Wait for modal animation
    const confirmButton = mockedPage.getByRole('button', { name: /Confirm/i });
    await confirmButton.click({ force: true });

    // Wait for modal to close
    await expect(editModal).not.toBeVisible({ timeout: 5000 });

    // URL should not contain any modal parameters
    await expect(mockedPage).not.toHaveURL(/.*\?modal=/);
  });

  test('shows loading state while fetching controls', async ({ page }) => {
    await mockRoutes.config(page);
    let resolveControls: () => void;
    const controlsPromise = new Promise<void>((resolve) => {
      resolveControls = resolve;
    });

    // Mock agent controls - wait for manual trigger
    await page.route('**/api/v1/agents/*/controls', async (route) => {
      await controlsPromise;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockData.controls),
      });
    });

    // Mock single agent (registered after controls route)
    await page.route('**/api/v1/agents/*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockData.agent),
      });
    });

    await page.goto(agentUrl);

    // Check for loading indicator (controls request is blocked, so loading state is guaranteed)
    await expect(page.getByText('Loading controls...')).toBeVisible();

    // Release the controls request
    resolveControls!();

    // Wait for controls to load
    await expect(page.getByRole('table')).toBeVisible();
  });

  test('handles agent not found error', async ({ page }) => {
    await mockRoutes.config(page);
    // Mock controls to return 404
    await page.route('**/api/v1/agents/*/controls', async (route) => {
      await route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Agent not found' }),
      });
    });

    // Mock agent to return 404
    await page.route('**/api/v1/agents/*', async (route) => {
      await route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Agent not found' }),
      });
    });

    await page.goto(agentUrl);

    // Check for error message
    await expect(page.getByText('Error loading agent')).toBeVisible();
  });

  test('can switch between tabs', async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Click Stats tab
    await mockedPage.getByRole('tab', { name: /Monitor/i }).click();
    // Check for summary card metrics to verify monitor tab is displayed (use first() to get summary card, not table header)
    await expect(mockedPage.getByText('Executions').first()).toBeVisible();
    await expect(mockedPage.getByText('Triggers').first()).toBeVisible();

    // Switch back to Controls
    await mockedPage.getByRole('tab', { name: /Controls/i }).click();
    await expect(mockedPage.getByRole('table')).toBeVisible();
  });

  test('opens edit control modal via URL query parameter', async ({
    mockedPage,
  }) => {
    // Mock empty stats to ensure controls tab is shown
    await mockRoutes.stats(mockedPage, { data: mockData.emptyStats });

    await mockedPage.goto(getAgentControlsUrl({ modal: 'edit', controlId: 1 }));

    // Edit modal should be visible
    const editModal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(editModal).toBeVisible();

    // URL should contain modal and controlId parameters
    await expect(mockedPage).toHaveURL(
      getAgentControlsUrl({ modal: 'edit', controlId: 1 })
    );
  });

  test('opens edit control modal when edit button is clicked', async ({
    mockedPage,
  }) => {
    await mockedPage.goto(agentUrl);

    // Click Controls tab (monitor might be shown by default if stats exist)
    await mockedPage.getByRole('tab', { name: 'Controls' }).click();

    // Wait for controls to load
    const controlsPanel = mockedPage.getByRole('tabpanel', {
      name: /Controls/i,
    });
    await expect(controlsPanel.getByRole('table')).toBeVisible();

    // Find and click the first edit button in a row (scope to controls panel)
    const rows = controlsPanel.locator('tbody tr');
    const firstRow = rows.first();

    // Scroll to the row to ensure it's in view
    await firstRow.scrollIntoViewIfNeeded();

    const editButton = firstRow.locator(
      'button:has(svg[class*="icon-pencil"])'
    );

    // If that doesn't work, try clicking any action button in the row
    if ((await editButton.count()) === 0) {
      const actionButtons = firstRow.locator('button').last();
      await actionButtons.click();
    } else {
      // Force click if button exists but might be hidden due to CSS
      await editButton.click({ force: true });
    }

    // Edit modal should be visible
    await expect(
      mockedPage.getByRole('dialog', { name: 'Edit Control' })
    ).toBeVisible();

    // URL should contain modal and controlId parameters
    await expect(mockedPage).toHaveURL(
      /\/agents\?id=agent-1&tab=controls&modal=edit&controlId=\d+/
    );
  });

  test('deletes control when delete is confirmed', async ({ mockedPage }) => {
    const controlToDelete = mockData.controls.controls.find(
      (c) => c.name === 'Rate Limiter'
    );
    if (!controlToDelete) throw new Error('Rate Limiter not in mock data');
    const deletedControlId = controlToDelete.id;

    // Agent controls: first GET returns full list, refetch after delete returns list without deleted control
    let agentControlsCallCount = 0;
    await mockedPage.route(
      '**/api/v1/agents/*/controls',
      async (route, request) => {
        if (request.method() !== 'GET') {
          await route.continue();
          return;
        }
        agentControlsCallCount += 1;
        const controls =
          agentControlsCallCount <= 1
            ? mockData.controls.controls
            : mockData.controls.controls.filter(
                (c) => c.id !== deletedControlId
              );
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ controls }),
        });
      }
    );

    await mockedPage.route(
      '**/api/v1/agents/*/controls/*',
      async (route, request) => {
        if (request.method() === 'DELETE') {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              success: true,
              removed_direct_association: true,
              control_still_active: false,
            }),
          });
        } else {
          await route.continue();
        }
      }
    );

    await mockedPage.goto(agentUrl);

    await mockedPage.getByRole('tab', { name: 'Controls' }).click();

    const controlsPanel = mockedPage.getByRole('tabpanel', {
      name: /Controls/i,
    });
    await expect(controlsPanel.getByRole('table')).toBeVisible();

    const targetRow = controlsPanel.locator('tr', {
      hasText: 'Rate Limiter',
    });
    await targetRow.scrollIntoViewIfNeeded();

    const deleteButton = targetRow.getByRole('button', {
      name: 'Remove control from agent',
    });
    await deleteButton.click();

    const confirmModal = mockedPage.getByRole('dialog', {
      name: /Remove control from agent\?/i,
    });
    await expect(confirmModal).toBeVisible();
    await expect(
      confirmModal.getByText(/does not delete the control globally/i)
    ).toBeVisible();

    const deleteRequest = mockedPage.waitForRequest(
      (request) =>
        request.method() === 'DELETE' &&
        new RegExp(
          `/api/v1/agents/[^/]+/controls/${deletedControlId}(\\?|$)`
        ).test(request.url()),
      { timeout: 5000 }
    );

    await confirmModal.getByRole('button', { name: 'Remove' }).click();

    const request = await deleteRequest;
    expect(request.url()).toMatch(
      new RegExp(`/api/v1/agents/[^/]+/controls/${deletedControlId}(\\?|$)`)
    );
    expect(request.method()).toBe('DELETE');

    await expect(confirmModal).not.toBeVisible({ timeout: 5000 });

    // Refetched list should not contain the deleted control
    await expect(controlsPanel.getByText('Rate Limiter')).not.toBeVisible();
    await expect(controlsPanel.getByText('PII Detection')).toBeVisible();
    await expect(controlsPanel.getByText('SQL Injection Guard')).toBeVisible();
  });

  test('edit control modal pre-fills scope and execution fields', async ({
    mockedPage,
  }) => {
    await mockedPage.goto(agentUrl);

    // Click Controls tab (monitor might be shown by default if stats exist)
    await mockedPage.getByRole('tab', { name: 'Controls' }).click();

    // Wait for controls to load
    const controlsPanel = mockedPage.getByRole('tabpanel', {
      name: /Controls/i,
    });
    await expect(controlsPanel.getByRole('table')).toBeVisible();

    // Find the row for "SQL Injection Guard" and click its edit button (scope to controls panel)
    const targetRow = controlsPanel.locator('tr', {
      hasText: 'SQL Injection Guard',
    });

    // Scroll to the row to ensure it's in view
    await targetRow.scrollIntoViewIfNeeded();

    const editButton = targetRow.locator(
      'button:has(svg[class*="icon-pencil"])'
    );

    if ((await editButton.count()) === 0) {
      await targetRow.locator('button').last().click();
    } else {
      // Force click if button exists but might be hidden due to CSS
      await editButton.click({ force: true });
    }

    const modal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(modal).toBeVisible();

    await expect(modal.getByText('Step types')).toBeVisible();
    await expect(modal.getByText('Stages')).toBeVisible();
    await expect(modal.getByText('Step name')).toBeVisible();
    await expect(modal.getByText('Regex')).toBeVisible();
    await expect(modal.getByText('Execution environment')).toBeVisible();

    await expect(modal.getByText('tool', { exact: true })).toBeVisible();
    await expect(
      modal.getByText('Pre (before execution)', { exact: true })
    ).toBeVisible();
    // Step name: mock has both step_names and step_name_regex; form shows names mode by default.
    await expect(
      modal.locator('p', { hasText: 'database_query' })
    ).toBeVisible();
    // Execution environment is a Select; assert label is visible (selected value may be in closed dropdown)
    const executionLabel = modal.getByText('Execution environment', {
      exact: true,
    });
    await executionLabel.scrollIntoViewIfNeeded();
    await expect(executionLabel).toBeVisible();
  });

  test('leaf controls with unknown evaluators still expose JSON editing', async ({
    mockedPage,
  }) => {
    const unknownEvaluatorControl: Control = {
      id: 42,
      name: 'External Guard',
      control: {
        description: 'Uses an external evaluator without a custom form',
        enabled: true,
        execution: 'server',
        scope: { step_types: ['llm'], stages: ['post'] },
        condition: {
          selector: { path: 'output' },
          evaluator: {
            name: 'vendor.external',
            config: { threshold: 0.7, mode: 'strict' },
          },
        },
        action: { decision: 'deny' },
        tags: ['external'],
      },
    };
    const unknownControls: AgentControlsResponse = {
      controls: [unknownEvaluatorControl],
    };

    await mockRoutes.agent(mockedPage, {
      controls: { data: unknownControls },
    });
    await mockedPage.route('**/api/v1/controls/42/data', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: unknownEvaluatorControl.control }),
      });
    });

    await mockedPage.goto(
      getAgentControlsUrl({ modal: 'edit', controlId: 42 })
    );

    const modal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(modal).toBeVisible();
    await expect(
      modal.getByText(
        'No form available for this evaluator. Use JSON view to configure.'
      )
    ).toBeVisible();

    await modal.getByText('JSON', { exact: true }).click();
    await expect(modal.getByTestId('raw-json-textarea')).toBeVisible();
    await expect(
      modal.getByText('Condition editing unavailable')
    ).not.toBeVisible();
  });

  test('controls can be edited through the full JSON editor', async ({
    mockedPage,
  }) => {
    const compositeControl: Control = {
      id: 77,
      name: 'Risk Escalation Guard',
      control: {
        description: 'Escalates high-risk interactions',
        enabled: true,
        execution: 'server',
        scope: { step_types: ['llm'], stages: ['post'] },
        condition: {
          and: [
            {
              selector: { path: 'context.risk_level' },
              evaluator: {
                name: 'list',
                config: {
                  values: ['high', 'critical'],
                  logic: 'any',
                  match_on: 'match',
                },
              },
            },
            {
              not: {
                selector: { path: 'context.user_role' },
                evaluator: {
                  name: 'list',
                  config: {
                    values: ['admin'],
                    logic: 'any',
                    match_on: 'match',
                  },
                },
              },
            },
          ],
        },
        action: { decision: 'deny' },
        tags: ['risk'],
      },
    };
    const compositeControls: AgentControlsResponse = {
      controls: [compositeControl],
    };
    const updatedCondition = {
      or: [
        {
          selector: { path: 'context.risk_level' },
          evaluator: {
            name: 'list',
            config: {
              values: ['critical'],
              logic: 'any',
              match_on: 'match',
            },
          },
        },
        {
          selector: { path: 'output' },
          evaluator: {
            name: 'regex',
            config: { pattern: 'urgent' },
          },
        },
      ],
    };

    let updateRequestBody: Record<string, unknown> | null = null;

    await mockRoutes.agent(mockedPage, {
      controls: { data: compositeControls },
    });
    await mockedPage.route(
      '**/api/v1/controls/77/data',
      async (route, request) => {
        if (request.method() === 'GET') {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ data: compositeControl.control }),
          });
          return;
        }

        if (request.method() === 'PUT') {
          updateRequestBody = (await request.postDataJSON()) as Record<
            string,
            unknown
          >;
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ success: true }),
          });
          return;
        }

        await route.continue();
      }
    );

    await mockedPage.goto(
      getAgentControlsUrl({ modal: 'edit', controlId: 77 })
    );

    const modal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(modal).toBeVisible();
    await modal.getByText('Full JSON', { exact: true }).click();
    await expect(modal.getByTestId('control-json-textarea')).toBeVisible();

    await setJsonEditorValue(
      mockedPage,
      'control-json-textarea',
      JSON.stringify(
        {
          ...compositeControl.control,
          description: 'Updated in full JSON mode',
          condition: updatedCondition,
        },
        null,
        2
      )
    );

    await modal.getByRole('button', { name: /Save/i }).click();
    await mockedPage.getByRole('button', { name: /Confirm/i }).click({
      force: true,
    });

    await expect.poll(() => updateRequestBody).not.toBeNull();

    expect(updateRequestBody).toMatchObject({
      data: {
        description: 'Updated in full JSON mode',
        condition: updatedCondition,
      },
    });
  });

  test('full JSON Monaco formatting preserves commas inside string values', async ({
    mockedPage,
  }) => {
    const control = mockData.controls.controls[0]!;

    await mockedPage.goto(
      getAgentControlsUrl({ modal: 'edit', controlId: String(control.id) })
    );

    const modal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(modal).toBeVisible();
    await modal.getByText('Full JSON', { exact: true }).click();

    await setJsonEditorValue(
      mockedPage,
      'control-json-textarea',
      JSON.stringify(
        {
          ...control.control,
          condition: {
            selector: { path: 'output' },
            evaluator: {
              name: 'regex',
              config: { pattern: 'a,}' },
            },
          },
        },
        null,
        2
      )
    );

    await modal.getByRole('button', { name: 'Format document' }).click();

    const after = JSON.parse(
      await getJsonEditorValue(mockedPage, 'control-json-textarea')
    ) as {
      condition: { evaluator: { config: { pattern: string } } };
    };
    expect(after.condition.evaluator.config.pattern).toBe('a,}');
  });

  test('full JSON editor always uses Monaco', async ({ mockedPage }) => {
    const control = mockData.controls.controls[0]!;

    await mockedPage.addInitScript(() => {
      window.localStorage.setItem('editControl.jsonEditorEngine', 'codemirror');
    });

    await mockedPage.goto(
      getAgentControlsUrl({ modal: 'edit', controlId: String(control.id) })
    );

    const modal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(modal).toBeVisible();
    await modal.getByText('Full JSON', { exact: true }).click();

    await expect(modal.getByText('CodeMirror', { exact: true })).toHaveCount(0);

    const editor = modal.getByTestId('control-json-textarea');
    await expect(editor).toBeVisible();
    await mockedPage.waitForFunction((selector) => {
      const element = document.querySelector(`[data-testid="${selector}"]`) as {
        __getJsonEditorLanguageId?: () => string | null;
        __isJsonEditorReady?: () => boolean;
      } | null;

      return (
        typeof element?.__getJsonEditorLanguageId === 'function' &&
        element.__isJsonEditorReady?.() === true
      );
    }, 'control-json-textarea');

    const languageId = await editor.evaluate((element) => {
      const target = element as {
        __getJsonEditorLanguageId?: () => string | null;
      };

      return target.__getJsonEditorLanguageId?.() ?? null;
    });

    expect(languageId).toBe('json');
  });

  test('full JSON editor suggests recursive condition keys', async ({
    mockedPage,
  }) => {
    const compositeControl: Control = {
      id: 78,
      name: 'Condition Autocomplete',
      control: {
        description: 'Autocomplete condition editing',
        enabled: true,
        execution: 'server',
        scope: { step_types: ['llm'], stages: ['post'] },
        condition: {
          selector: { path: 'output' },
          evaluator: {
            name: 'regex',
            config: { pattern: '.*' },
          },
        },
        action: { decision: 'deny' },
        tags: [],
      },
    };

    await mockRoutes.agent(mockedPage, {
      controls: { data: { controls: [compositeControl] } },
      agent: { data: mockData.agentWithSteps },
    });
    await mockedPage.route('**/api/v1/controls/78/data', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: compositeControl.control }),
      });
    });

    await mockedPage.goto(
      getAgentControlsUrl({ modal: 'edit', controlId: 78 })
    );

    const modal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(modal).toBeVisible();
    await modal.getByText('Full JSON', { exact: true }).click();

    await setJsonEditorValue(
      mockedPage,
      'control-json-textarea',
      `{
  "description": "Autocomplete condition editing",
  "enabled": true,
  "execution": "server",
  "condition": {
    
  },
  "action": {
    "decision": "deny"
  },
  "tags": []
}`
    );

    const suggestions = await getJsonEditorSuggestions(
      mockedPage,
      'control-json-textarea',
      6,
      5
    );
    const labels = suggestions.map((item) => item.label);

    expect(labels).toEqual(
      expect.arrayContaining(['selector', 'evaluator', 'and', 'or', 'not'])
    );
  });

  test('full JSON editor suggests condition keys while replacing a partial key', async ({
    mockedPage,
  }) => {
    const compositeControl: Control = {
      id: 79,
      name: 'Partial Condition Key Autocomplete',
      control: {
        description: 'Autocomplete partial condition keys',
        enabled: true,
        execution: 'server',
        condition: {
          selector: { path: 'output' },
          evaluator: {
            name: 'regex',
            config: { pattern: '.*' },
          },
        },
        action: { decision: 'deny' },
        tags: [],
      },
    };

    await mockRoutes.agent(mockedPage, {
      controls: { data: { controls: [compositeControl] } },
      agent: { data: mockData.agentWithSteps },
    });
    await mockedPage.route('**/api/v1/controls/79/data', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: compositeControl.control }),
      });
    });

    await mockedPage.goto(
      getAgentControlsUrl({ modal: 'edit', controlId: 79 })
    );

    const modal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(modal).toBeVisible();
    await modal.getByText('Full JSON', { exact: true }).click();

    await setJsonEditorValue(
      mockedPage,
      'control-json-textarea',
      `{
  "description": "Autocomplete partial condition keys",
  "enabled": true,
  "execution": "server",
  "condition": {
    "s": {}
  },
  "action": {
    "decision": "deny"
  },
  "tags": []
}`
    );

    const suggestions = await getJsonEditorSuggestions(
      mockedPage,
      'control-json-textarea',
      6,
      6
    );
    const labels = suggestions.map((item) => item.label);

    expect(labels).toEqual(
      expect.arrayContaining(['selector', 'evaluator', 'and', 'or', 'not'])
    );
  });

  test('full JSON editor suggests condition keys for incomplete property keys', async ({
    mockedPage,
  }) => {
    const compositeControl: Control = {
      id: 81,
      name: 'Incomplete Condition Key Suggestions',
      control: {
        description: 'Show incomplete condition key suggestions',
        enabled: true,
        execution: 'server',
        condition: {
          selector: { path: 'output' },
          evaluator: {
            name: 'regex',
            config: { pattern: '.*' },
          },
        },
        action: { decision: 'deny' },
        tags: [],
      },
    };

    await mockRoutes.agent(mockedPage, {
      controls: { data: { controls: [compositeControl] } },
      agent: { data: mockData.agentWithSteps },
    });
    await mockedPage.route('**/api/v1/controls/81/data', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: compositeControl.control }),
      });
    });

    await mockedPage.goto(
      getAgentControlsUrl({ modal: 'edit', controlId: 81 })
    );

    const modal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(modal).toBeVisible();
    await modal.getByText('Full JSON', { exact: true }).click();

    await setJsonEditorValue(
      mockedPage,
      'control-json-textarea',
      `{
  "description": "Show incomplete condition key suggestions",
  "enabled": true,
  "execution": "server",
  "condition": {
    "s
  },
  "action": {
    "decision": "deny"
  },
  "tags": []
}`
    );

    const suggestions = await getJsonEditorSuggestions(
      mockedPage,
      'control-json-textarea',
      6,
      6
    );
    const labels = suggestions.map((item) => item.label);

    expect(labels).toEqual(
      expect.arrayContaining(['selector', 'evaluator', 'and', 'or', 'not'])
    );
  });

  test('full JSON editor suggest button inserts valid selector JSON', async ({
    mockedPage,
  }) => {
    const compositeControl: Control = {
      id: 82,
      name: 'Suggest Button Autocomplete',
      control: {
        description: 'Open autocomplete from the suggest button',
        enabled: true,
        execution: 'server',
        condition: {
          selector: { path: 'output' },
          evaluator: {
            name: 'regex',
            config: { pattern: '.*' },
          },
        },
        action: { decision: 'deny' },
        tags: [],
      },
    };

    await mockRoutes.agent(mockedPage, {
      controls: { data: { controls: [compositeControl] } },
      agent: { data: mockData.agentWithSteps },
    });
    await mockedPage.route('**/api/v1/controls/82/data', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: compositeControl.control }),
      });
    });

    await mockedPage.goto(
      getAgentControlsUrl({ modal: 'edit', controlId: 82 })
    );

    const modal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(modal).toBeVisible();
    await modal.getByText('Full JSON', { exact: true }).click();

    await setJsonEditorValue(
      mockedPage,
      'control-json-textarea',
      `{
  "description": "Open autocomplete from the suggest button",
  "enabled": true,
  "execution": "server",
  "condition": {
    "s
  },
  "action": {
    "decision": "deny"
  },
  "tags": []
}`
    );

    await focusJsonEditorAt(mockedPage, 'control-json-textarea', 6, 6);

    const suggestions = await getJsonEditorSuggestions(
      mockedPage,
      'control-json-textarea',
      6,
      6
    );
    const labels = suggestions.map((item) => item.label);

    expect(labels).toContain('selector');
  });

  test('full JSON editor suggests evaluator keys at property position', async ({
    mockedPage,
  }) => {
    const compositeControl: Control = {
      id: 83,
      name: 'Evaluator Suggestion Autocomplete',
      control: {
        description: 'Insert evaluator objects from autocomplete',
        enabled: true,
        execution: 'server',
        condition: {
          selector: { path: 'output' },
          evaluator: {
            name: 'regex',
            config: { pattern: '.*' },
          },
        },
        action: { decision: 'deny' },
        tags: [],
      },
    };

    await mockRoutes.agent(mockedPage, {
      controls: { data: { controls: [compositeControl] } },
      agent: { data: mockData.agentWithSteps },
    });
    await mockedPage.route('**/api/v1/controls/83/data', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: compositeControl.control }),
      });
    });

    await mockedPage.goto(
      getAgentControlsUrl({ modal: 'edit', controlId: 83 })
    );

    const modal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(modal).toBeVisible();
    await modal.getByText('Full JSON', { exact: true }).click();

    await setJsonEditorValue(
      mockedPage,
      'control-json-textarea',
      `{
  "description": "Insert evaluator objects from autocomplete",
  "enabled": true,
  "execution": "server",
  "condition": {
    "e
  },
  "action": {
    "decision": "deny"
  },
  "tags": []
}`
    );

    await focusJsonEditorAt(mockedPage, 'control-json-textarea', 6, 6);

    const suggestions = await getJsonEditorSuggestions(
      mockedPage,
      'control-json-textarea',
      6,
      6
    );
    const labels = suggestions.map((item) => item.label);

    expect(labels).toContain('evaluator');
  });

  test('full JSON editor suggests evaluator config keys from evaluator schema', async ({
    mockedPage,
  }) => {
    const compositeControl: Control = {
      id: 80,
      name: 'Config Schema Autocomplete',
      control: {
        description: 'Autocomplete evaluator config keys',
        enabled: true,
        execution: 'server',
        condition: {
          selector: { path: 'output' },
          evaluator: {
            name: 'list',
            config: { values: ['high'] },
          },
        },
        action: { decision: 'deny' },
        tags: [],
      },
    };

    await mockRoutes.agent(mockedPage, {
      controls: { data: { controls: [compositeControl] } },
      agent: { data: mockData.agentWithSteps },
    });
    await mockedPage.route('**/api/v1/controls/80/data', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: compositeControl.control }),
      });
    });

    await mockedPage.goto(
      getAgentControlsUrl({ modal: 'edit', controlId: 80 })
    );

    const modal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(modal).toBeVisible();
    await modal.getByText('Full JSON', { exact: true }).click();

    await setJsonEditorValue(
      mockedPage,
      'control-json-textarea',
      `{
  "description": "Autocomplete evaluator config keys",
  "enabled": true,
  "execution": "server",
  "condition": {
    "selector": {
      "path": "output"
    },
    "evaluator": {
      "name": "list",
      "config": {
        
      }
    }
  },
  "action": {
    "decision": "deny"
  },
  "tags": []
}`
    );

    const suggestions = await getJsonEditorSuggestions(
      mockedPage,
      'control-json-textarea',
      12,
      9
    );
    const labels = suggestions.map((item) => item.label);

    expect(labels).toEqual(
      expect.arrayContaining(['values', 'logic', 'match_on'])
    );
  });

  test('full JSON editor filters $schema and duplicate properties from suggestions', async ({
    mockedPage,
  }) => {
    const compositeControl: Control = {
      id: 84,
      name: 'Property Filter Test',
      control: {
        description: 'Test property filtering',
        enabled: true,
        execution: 'server',
        condition: {
          selector: { path: 'output' },
          evaluator: { name: 'regex', config: { pattern: '.*' } },
        },
        action: { decision: 'deny' },
        tags: [],
      },
    };

    await mockRoutes.agent(mockedPage, {
      controls: { data: { controls: [compositeControl] } },
      agent: { data: mockData.agentWithSteps },
    });
    await mockedPage.route('**/api/v1/controls/84/data', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: compositeControl.control }),
      });
    });

    await mockedPage.goto(
      getAgentControlsUrl({ modal: 'edit', controlId: 84 })
    );

    const modal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(modal).toBeVisible();
    await modal.getByText('Full JSON', { exact: true }).click();

    // Suggestions at root level inside a populated object should NOT include
    // existing properties or $schema
    const suggestions = await getJsonEditorSuggestions(
      mockedPage,
      'control-json-textarea',
      2,
      3
    );
    const labels = suggestions.map((item) => item.label);

    // $schema should be filtered
    expect(labels).not.toContain('$schema');
    // Already-present properties should be filtered
    expect(labels).not.toContain('description');
    expect(labels).not.toContain('enabled');
    expect(labels).not.toContain('condition');
    expect(labels).not.toContain('action');
  });

  test('full JSON editor suggests evaluator names inside evaluator name field', async ({
    mockedPage,
  }) => {
    const compositeControl: Control = {
      id: 85,
      name: 'Evaluator Name Suggestions',
      control: {
        description: 'Test evaluator name suggestions',
        enabled: true,
        execution: 'server',
        condition: {
          selector: { path: 'output' },
          evaluator: { name: 'regex', config: { pattern: '.*' } },
        },
        action: { decision: 'deny' },
        tags: [],
      },
    };

    await mockRoutes.agent(mockedPage, {
      controls: { data: { controls: [compositeControl] } },
      agent: { data: mockData.agentWithSteps },
    });
    await mockedPage.route('**/api/v1/controls/85/data', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: compositeControl.control }),
      });
    });

    await mockedPage.goto(
      getAgentControlsUrl({ modal: 'edit', controlId: 85 })
    );

    const modal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(modal).toBeVisible();
    await modal.getByText('Full JSON', { exact: true }).click();

    // Find the evaluator name line and get suggestions inside it
    await setJsonEditorValue(
      mockedPage,
      'control-json-textarea',
      `{
  "condition": {
    "selector": { "path": "output" },
    "evaluator": {
      "name": "",
      "config": {}
    }
  },
  "action": { "decision": "deny" },
  "execution": "server",
  "enabled": true
}`
    );

    const suggestions = await getJsonEditorSuggestions(
      mockedPage,
      'control-json-textarea',
      5,
      15
    );
    const labels = suggestions.map((item) => item.label);

    // Should include available evaluator names
    expect(labels).toContain('regex');
    expect(labels).toContain('list');
    expect(labels).toContain('json');
    expect(labels).toContain('sql');
  });

  test('full JSON editor suggests selector paths inside path field', async ({
    mockedPage,
  }) => {
    const compositeControl: Control = {
      id: 86,
      name: 'Selector Path Suggestions',
      control: {
        description: 'Test selector path suggestions',
        enabled: true,
        execution: 'server',
        condition: {
          selector: { path: '' },
          evaluator: { name: 'regex', config: { pattern: '.*' } },
        },
        action: { decision: 'deny' },
        tags: [],
      },
    };

    await mockRoutes.agent(mockedPage, {
      controls: { data: { controls: [compositeControl] } },
      agent: { data: mockData.agentWithSteps },
    });
    await mockedPage.route('**/api/v1/controls/86/data', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: compositeControl.control }),
      });
    });

    await mockedPage.goto(
      getAgentControlsUrl({ modal: 'edit', controlId: 86 })
    );

    const modal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(modal).toBeVisible();
    await modal.getByText('Full JSON', { exact: true }).click();

    await setJsonEditorValue(
      mockedPage,
      'control-json-textarea',
      `{
  "condition": {
    "selector": { "path": "" },
    "evaluator": { "name": "regex", "config": {} }
  },
  "action": { "decision": "deny" },
  "execution": "server",
  "enabled": true
}`
    );

    const suggestions = await getJsonEditorSuggestions(
      mockedPage,
      'control-json-textarea',
      3,
      28
    );
    const labels = suggestions.map((item) => item.label);

    expect(labels).toContain('*');
    expect(labels).toContain('input');
    expect(labels).toContain('output');
    expect(labels).toContain('context');
  });

  test('full JSON editor suggests all root properties in empty object', async ({
    mockedPage,
  }) => {
    const compositeControl: Control = {
      id: 87,
      name: 'Root Property Suggestions',
      control: {
        description: 'Test root suggestions',
        enabled: true,
        execution: 'server',
        condition: {
          selector: { path: 'output' },
          evaluator: { name: 'regex', config: { pattern: '.*' } },
        },
        action: { decision: 'deny' },
        tags: [],
      },
    };

    await mockRoutes.agent(mockedPage, {
      controls: { data: { controls: [compositeControl] } },
      agent: { data: mockData.agentWithSteps },
    });
    await mockedPage.route('**/api/v1/controls/87/data', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: compositeControl.control }),
      });
    });

    await mockedPage.goto(
      getAgentControlsUrl({ modal: 'edit', controlId: 87 })
    );

    const modal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(modal).toBeVisible();
    await modal.getByText('Full JSON', { exact: true }).click();

    await setJsonEditorValue(
      mockedPage,
      'control-json-textarea',
      `{

}`
    );

    const suggestions = await getJsonEditorSuggestions(
      mockedPage,
      'control-json-textarea',
      2,
      3
    );
    const labels = suggestions.map((item) => item.label);

    expect(labels).toContain('description');
    expect(labels).toContain('enabled');
    expect(labels).toContain('execution');
    expect(labels).toContain('scope');
    expect(labels).toContain('condition');
    expect(labels).toContain('action');
    expect(labels).toContain('tags');
    expect(labels).not.toContain('$schema');
  });

  test('disables Form switch when JSON is invalid', async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Click Controls tab (monitor might be shown by default if stats exist)
    await mockedPage.getByRole('tab', { name: 'Controls' }).click();

    // Open edit modal
    const controlsPanel = mockedPage.getByRole('tabpanel', {
      name: /Controls/i,
    });
    await expect(controlsPanel.getByRole('table')).toBeVisible();
    const firstRow = controlsPanel.locator('tbody tr').first();
    await firstRow.scrollIntoViewIfNeeded();
    const editButton = firstRow.locator(
      'button:has(svg[class*="icon-pencil"])'
    );
    if ((await editButton.count()) === 0) {
      await firstRow.locator('button').last().click();
    } else {
      await editButton.click({ force: true });
    }

    const modal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(modal).toBeVisible();

    // Switch to JSON mode (Mantine hides the native radio; click the visible segment label)
    await modal.getByText('JSON', { exact: true }).click();

    // Enter invalid JSON
    await setJsonEditorValue(mockedPage, 'raw-json-textarea', '{');

    // Form option should be disabled when JSON is invalid (validation is debounced ~500ms)
    await expect(
      modal.getByRole('radio', { name: 'Form' }).last()
    ).toBeDisabled({
      timeout: 2000,
    });
  });

  test('valid JSON triggers validation call', async ({ mockedPage }) => {
    await mockedPage.goto(agentUrl);

    // Click Controls tab
    await mockedPage.getByRole('tab', { name: 'Controls' }).click();

    // Open edit modal
    const controlsPanel = mockedPage.getByRole('tabpanel', {
      name: /Controls/i,
    });
    await expect(controlsPanel.getByRole('table')).toBeVisible();
    const firstRow = controlsPanel.locator('tbody tr').first();
    await firstRow.scrollIntoViewIfNeeded();
    const editButton = firstRow.locator(
      'button:has(svg[class*="icon-pencil"])'
    );
    if ((await editButton.count()) === 0) {
      await firstRow.locator('button').last().click();
    } else {
      await editButton.click({ force: true });
    }

    const modal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(modal).toBeVisible();

    // Switch to JSON mode (Mantine hides the native radio; click the visible segment label)
    await modal.getByText('JSON', { exact: true }).click();

    // Validation is debounced (~500ms); start waiting for request before filling
    const validateRequest = mockedPage.waitForRequest(
      (request) =>
        request.url().includes('/api/v1/controls/validate') &&
        request.method() === 'POST',
      { timeout: 10000 }
    );

    await setJsonEditorValue(
      mockedPage,
      'raw-json-textarea',
      JSON.stringify({ pattern: '.*' }, null, 2)
    );

    await validateRequest;
  });
});

test.describe('Agent Detail - Empty State', () => {
  test('shows empty state when no controls exist', async ({ page }) => {
    await mockRoutes.config(page);
    // Type-safe empty controls response
    const emptyControlsResponse: AgentControlsResponse = { controls: [] };

    // Mock controls to return empty
    await page.route('**/api/v1/agents/*/controls', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(emptyControlsResponse),
      });
    });

    // Mock agent to return normally
    await page.route('**/api/v1/agents/*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockData.agent),
      });
    });

    await page.goto(getAgentRoute('agent-1', { tab: 'controls' }));

    // Check for empty state message
    await expect(page.getByText('No controls configured')).toBeVisible();
    await expect(
      page.getByText("This agent doesn't have any controls set up yet.")
    ).toBeVisible();

    // Empty state should have Add Control button (there are 2 - one in header, one in content)
    await expect(page.getByTestId('add-control-button').first()).toBeVisible();
  });
});
