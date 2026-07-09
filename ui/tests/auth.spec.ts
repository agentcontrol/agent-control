import {
  expect,
  mockApiRoutesWithAuthRequired,
  mockData,
  mockRoutes,
  test,
} from './fixtures';

test.describe('API key login flow', () => {
  test('shows login modal when server requires API key', async ({ page }) => {
    await mockApiRoutesWithAuthRequired(page);
    await page.goto('/');

    await expect(
      page.getByRole('heading', { name: 'Agent Control' })
    ).toBeVisible();
    await expect(
      page.getByText('Enter your API key to continue.')
    ).toBeVisible();
    await expect(page.getByPlaceholder('Enter your API key')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible();

    // Main app content should not be visible
    await expect(
      page.getByRole('heading', { name: 'Agents overview' })
    ).not.toBeVisible();
  });

  test('shows main app after successful login with valid API key', async ({
    page,
  }) => {
    await mockApiRoutesWithAuthRequired(page);
    await mockRoutes.login(page, { authenticated: true, is_admin: false });
    await page.goto('/');

    // Modal is shown first
    await expect(
      page.getByText('Enter your API key to continue.')
    ).toBeVisible();

    await page.getByPlaceholder('Enter your API key').fill('valid-key');
    await page.getByRole('button', { name: 'Sign in' }).click();

    // Authenticated users land on the DefenseClaw workspace, not the internal
    // synchronization-agent inventory.
    await expect(page.getByRole('heading', { name: 'Controls' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Monitor' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'My agents' })).toHaveCount(0);
    await expect(page.getByText('defenseclaw-policy-sync')).toHaveCount(0);
  });

  test('shows error when API key is invalid', async ({ page }) => {
    await mockApiRoutesWithAuthRequired(page);
    await mockRoutes.login(page, { authenticated: false });
    await page.goto('/');

    await page.getByPlaceholder('Enter your API key').fill('wrong-key');
    await page.getByRole('button', { name: 'Sign in' }).click();

    await expect(
      page.getByText('Invalid API key. Please check and try again.')
    ).toBeVisible({ timeout: 5000 });
    // Modal and form still visible
    await expect(
      page.getByRole('heading', { name: 'Agent Control' })
    ).toBeVisible();
  });

  test('restores a non-admin session as read-only', async ({ page }) => {
    await mockApiRoutesWithAuthRequired(page, {
      has_active_session: true,
      is_admin: false,
    });

    await page.goto('/agents?id=agent-1&tab=controls');

    await expect(
      page.getByRole('alert', { name: 'Administrator-managed rule buckets' })
    ).toBeVisible();
    await expect(page.getByTestId('add-control-button')).toHaveCount(0);
    await expect(page.getByLabel('Edit control')).toHaveCount(0);
    await expect(page.getByLabel('Remove control from agent')).toHaveCount(0);

    const assignedControlSwitches = page.getByRole('switch');
    await expect(assignedControlSwitches).toHaveCount(
      mockData.controls.controls.length
    );
    for (let index = 0; index < mockData.controls.controls.length; index += 1) {
      await expect(assignedControlSwitches.nth(index)).toBeDisabled();
    }
  });

  test('clears member-scoped spans before a different API key signs in', async ({
    page,
  }) => {
    await mockApiRoutesWithAuthRequired(page, {
      has_active_session: true,
      is_admin: false,
    });
    await mockRoutes.login(page, { authenticated: true, is_admin: false });
    await page.route('**/api/logout', async (route) => {
      await route.fulfill({ status: 204 });
    });

    let principal: 'first' | 'second' = 'first';
    let releaseSecondResponse: () => void = () => undefined;
    const secondResponseGate = new Promise<void>((resolve) => {
      releaseSecondResponse = resolve;
    });
    await page.route('**/api/v1/observability/events/query', async (route) => {
      if (principal === 'second') await secondResponseGate;
      const event = mockData.events.events[0];
      const prompt =
        principal === 'first' ? 'member-a-exact-span' : 'member-b-exact-span';
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...mockData.events,
          total: 1,
          events: [
            {
              ...event,
              control_execution_id: `execution-${principal}`,
              metadata: {
                ...event.metadata,
                blocked_input: { prompt },
              },
            },
          ],
        }),
      });
    });

    await page.goto('/agents?id=agent-1&tab=monitor');
    await expect(
      page.getByText('member-a-exact-span', { exact: true })
    ).toBeVisible();

    principal = 'second';
    await page.getByTitle('Sign out').click();
    await page.getByPlaceholder('Enter your API key').fill('member-b-key');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(
      page.getByRole('heading', { name: 'customer-support-bot' })
    ).toBeVisible();
    await expect(
      page.getByText('member-a-exact-span', { exact: true })
    ).toHaveCount(0);

    releaseSecondResponse();
    await expect(
      page.getByText('member-b-exact-span', { exact: true })
    ).toBeVisible();
  });
});
