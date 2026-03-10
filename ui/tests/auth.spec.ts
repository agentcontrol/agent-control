import {
  expect,
  mockApiRoutesWithAuthRequired,
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

    // After login, main app should be visible
    await expect(
      page.getByRole('heading', { name: 'Agents overview' })
    ).toBeVisible({ timeout: 5000 });
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
});
