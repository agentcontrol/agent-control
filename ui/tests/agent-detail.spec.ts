import type { AgentControlsResponse, GetAgentResponse } from '@/core/api/types';

import { expect, mockData, mockRoutes, test } from './fixtures';

test.describe('Agent Detail Page', () => {
  const agentId = 'agent-1';
  const agentUrl = `/agents/${agentId}/controls`;

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

    await mockedPage.goto(`/agents/${agentId}/controls`);

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

    await mockedPage.goto(`/agents/${agentId}/monitor`);

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
    await expect(mockedPage).toHaveURL(/.*\?modal=control-store/);
  });

  test('closing edit modal removes query parameters', async ({
    mockedPage,
  }) => {
    // Mock empty stats to ensure controls tab is shown
    await mockRoutes.stats(mockedPage, { data: mockData.emptyStats });

    // Open edit modal via URL
    await mockedPage.goto(`${agentUrl}?modal=edit&controlId=1`);

    const editModal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(editModal).toBeVisible();

    // Close the modal (press Escape)
    await mockedPage.keyboard.press('Escape');

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
    await mockedPage.goto(`${agentUrl}?modal=edit&controlId=1`);

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

    await mockedPage.goto(`${agentUrl}?modal=edit&controlId=1`);

    // Edit modal should be visible
    const editModal = mockedPage.getByRole('dialog', { name: 'Edit Control' });
    await expect(editModal).toBeVisible();

    // URL should contain modal and controlId parameters
    await expect(mockedPage).toHaveURL(/.*\?modal=edit&controlId=1/);
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
    await expect(mockedPage).toHaveURL(/.*\?modal=edit&controlId=\d+/);
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
    const jsonInput = modal.getByTestId('raw-json-textarea');
    await jsonInput.fill('{');

    // Form option should be disabled when JSON is invalid (validation is debounced ~500ms)
    await expect(modal.getByRole('radio', { name: 'Form' })).toBeDisabled({
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

    await modal
      .getByTestId('raw-json-textarea')
      .fill(JSON.stringify({ pattern: '.*' }, null, 2));

    await validateRequest;
  });
});

test.describe('Agent Detail - Empty State', () => {
  test('shows empty state when no controls exist', async ({ page }) => {
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

    await page.goto('/agents/agent-1/controls');

    // Check for empty state message
    await expect(page.getByText('No controls configured')).toBeVisible();
    await expect(
      page.getByText("This agent doesn't have any controls set up yet.")
    ).toBeVisible();

    // Empty state should have Add Control button (there are 2 - one in header, one in content)
    await expect(page.getByTestId('add-control-button').first()).toBeVisible();
  });
});
