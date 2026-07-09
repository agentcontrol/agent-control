import type { Page } from '@playwright/test';

import type {
  AccessUserResponse,
  ApiKeyControlGrant,
  ApiKeyResponse,
  CreateAccessUserRequest,
  CreateApiKeyRequest,
  UpdateAccessUserRequest,
  UpdateControlGrantsRequest,
} from '@/core/api/access';

import {
  expect,
  mockApiRoutesWithAuthRequired,
  mockRoutes,
  test,
} from './fixtures';

type AccessMockState = {
  users: AccessUserResponse[];
  apiKeys: Record<string, ApiKeyResponse[]>;
  grants: Record<string, ApiKeyControlGrant>;
};

const memberUser: AccessUserResponse = {
  id: 'user-member',
  name: 'DefenseClaw operator',
  role: 'member',
  enabled: true,
  created_at: '2026-07-09T12:00:00Z',
};

const adminUser: AccessUserResponse = {
  id: 'user-admin',
  name: 'Platform administrator',
  role: 'admin',
  enabled: true,
  created_at: '2026-07-08T12:00:00Z',
};

const memberApiKey: ApiKeyResponse = {
  id: 'key-member',
  user_id: memberUser.id,
  name: 'DefenseClaw production',
  key_prefix: 'ac_live_3f4c',
  enabled: true,
  expires_at: null,
  revoked_at: null,
  created_at: '2026-07-09T12:30:00Z',
};

function createAccessMockState(): AccessMockState {
  return {
    users: [memberUser, adminUser],
    apiKeys: {
      [memberUser.id]: [memberApiKey],
      [adminUser.id]: [],
    },
    grants: {
      [memberApiKey.id]: {
        api_key_id: memberApiKey.id,
        control_ids: [1],
      },
    },
  };
}

async function fulfillJson(
  route: Parameters<Parameters<Page['route']>[1]>[0],
  body: unknown,
  status = 200
) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

async function mockAccessApi(page: Page, state: AccessMockState) {
  await page.route('**/api/v1/admin/access/**', async (route, request) => {
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (path === '/api/v1/admin/access/users') {
      if (method === 'GET') {
        await fulfillJson(route, { users: state.users });
        return;
      }
      if (method === 'POST') {
        const body = (await request.postDataJSON()) as CreateAccessUserRequest;
        const created: AccessUserResponse = {
          id: `user-${state.users.length + 1}`,
          name: body.name,
          role: body.role,
          enabled: true,
          created_at: '2026-07-09T13:00:00Z',
        };
        state.users = [...state.users, created];
        state.apiKeys[created.id] = [];
        await fulfillJson(route, created, 201);
        return;
      }
    }

    const userMatch = path.match(/^\/api\/v1\/admin\/access\/users\/([^/]+)$/);
    if (userMatch && method === 'PATCH') {
      const userId = userMatch[1];
      const body = (await request.postDataJSON()) as UpdateAccessUserRequest;
      const user = state.users.find((candidate) => candidate.id === userId);
      if (!user) {
        await fulfillJson(route, { detail: 'Not found' }, 404);
        return;
      }
      Object.assign(user, body);
      await fulfillJson(route, user);
      return;
    }

    const userKeysMatch = path.match(
      /^\/api\/v1\/admin\/access\/users\/([^/]+)\/api-keys$/
    );
    if (userKeysMatch) {
      const userId = userKeysMatch[1];
      if (method === 'GET') {
        await fulfillJson(route, { api_keys: state.apiKeys[userId] ?? [] });
        return;
      }
      if (method === 'POST') {
        const body = (await request.postDataJSON()) as CreateApiKeyRequest;
        const apiKey: ApiKeyResponse = {
          id: `key-${userId}-${(state.apiKeys[userId]?.length ?? 0) + 1}`,
          user_id: userId,
          name: body.name,
          key_prefix: 'ac_live_new',
          enabled: true,
          expires_at: body.expires_at ?? null,
          revoked_at: null,
          created_at: '2026-07-09T13:05:00Z',
        };
        state.apiKeys[userId] = [...(state.apiKeys[userId] ?? []), apiKey];
        state.grants[apiKey.id] = {
          api_key_id: apiKey.id,
          control_ids: [],
        };
        await fulfillJson(
          route,
          { api_key: apiKey, secret: 'ac_test_generated_secret' },
          201
        );
        return;
      }
    }

    const keyMatch = path.match(
      /^\/api\/v1\/admin\/access\/api-keys\/([^/]+)$/
    );
    if (keyMatch && method === 'DELETE') {
      const apiKeyId = keyMatch[1];
      for (const keys of Object.values(state.apiKeys)) {
        const key = keys.find((candidate) => candidate.id === apiKeyId);
        if (key) {
          key.enabled = false;
          key.revoked_at = '2026-07-09T13:10:00Z';
        }
      }
      await route.fulfill({ status: 204 });
      return;
    }

    const grantMatch = path.match(
      /^\/api\/v1\/admin\/access\/api-keys\/([^/]+)\/control-grants$/
    );
    if (grantMatch) {
      const apiKeyId = grantMatch[1];
      if (method === 'GET') {
        await fulfillJson(
          route,
          state.grants[apiKeyId] ?? {
            api_key_id: apiKeyId,
            control_ids: [],
          }
        );
        return;
      }
      if (method === 'PUT') {
        const body =
          (await request.postDataJSON()) as UpdateControlGrantsRequest;
        const grant = {
          api_key_id: apiKeyId,
          control_ids: body.control_ids ?? [],
        };
        state.grants[apiKeyId] = grant;
        await fulfillJson(route, grant);
        return;
      }
    }

    await fulfillJson(route, { detail: 'Unhandled mock route' }, 404);
  });
}

async function setupAdminPage(page: Page, state = createAccessMockState()) {
  await mockApiRoutesWithAuthRequired(page, {
    has_active_session: true,
    is_admin: true,
  });
  await mockAccessApi(page, state);
  return state;
}

test.describe('Access management', () => {
  test('shows users, API keys, and current rule bucket assignments to admins', async ({
    page,
  }) => {
    await setupAdminPage(page);
    await page.goto('/admin/access');

    await expect(page).toHaveURL(/\/admin\/access$/);
    await expect(page).toHaveTitle(/Agent Control/);
    await expect(
      page.getByRole('heading', { name: 'Access management' })
    ).toBeVisible();
    await expect(
      page.getByRole('link', { name: 'Access management' })
    ).toBeVisible();
    await expect(page.getByText('2 users')).toBeVisible();

    await page.getByRole('button', { name: /DefenseClaw operator/ }).click();

    await expect(page.getByText('DefenseClaw production')).toBeVisible();
    await expect(page.getByText('Prefix ac_live_3f4c')).toBeVisible();
    await expect(
      page
        .getByTestId(`api-key-${memberApiKey.id}`)
        .getByText('PII Detection', { exact: true })
    ).toBeVisible();
  });

  test('creates a user and shows a generated key exactly once with SDK guidance', async ({
    page,
  }) => {
    const state = await setupAdminPage(page);
    await page.goto('/admin/access');

    await page.getByLabel('Name').fill('Security reviewer');
    await page.getByTestId('create-access-user').click();

    await expect(
      page.getByRole('button', { name: /Security reviewer/ })
    ).toBeVisible();
    const createdUser = state.users.find(
      (user) => user.name === 'Security reviewer'
    );
    expect(createdUser).toBeDefined();

    await page.getByRole('button', { name: /Security reviewer/ }).click();
    const createKeyButton = page.getByTestId(
      `create-api-key-${createdUser?.id}`
    );
    await createKeyButton
      .locator('..')
      .getByLabel('Key name')
      .fill('Review workstation');
    await createKeyButton.click();

    await expect(
      page.getByRole('dialog', { name: 'API key created' })
    ).toBeVisible();
    await expect(
      page.getByText('ac_test_generated_secret', { exact: true })
    ).toBeVisible();
    await expect(
      page.getByText('AGENT_CONTROL_API_KEY', { exact: true })
    ).toBeVisible();
    await expect(
      page.getByText('defenseclaw keys set AGENT_CONTROL_API_KEY', {
        exact: true,
      })
    ).toBeVisible();

    await page.getByTestId('close-api-key-secret').click();
    await expect(
      page.getByText('ac_test_generated_secret', { exact: true })
    ).toHaveCount(0);
    await expect(page.getByText('Review workstation')).toBeVisible();
  });

  test('updates assigned rule buckets and revokes a key with confirmation', async ({
    page,
  }) => {
    const state = await setupAdminPage(page);
    await page.goto('/admin/access');
    await page.getByRole('button', { name: /DefenseClaw operator/ }).click();

    const grantsInput = page.getByLabel(
      'Assigned rule buckets for DefenseClaw production'
    );
    await grantsInput.click();
    await page.getByRole('option', { name: 'SQL Injection Guard' }).click();
    await page.getByTestId(`save-grants-${memberApiKey.id}`).click();

    await expect
      .poll(() => state.grants[memberApiKey.id].control_ids)
      .toEqual([1, 2]);

    await page.getByTestId(`revoke-api-key-${memberApiKey.id}`).click();
    await expect(
      page.getByRole('heading', { name: 'Revoke API key?' })
    ).toBeVisible();
    await page.getByRole('button', { name: 'Revoke key' }).click();

    await expect(
      page
        .getByTestId(`api-key-${memberApiKey.id}`)
        .getByText('Revoked', { exact: true })
    ).toBeVisible();
    await expect(
      page.getByLabel('Assigned rule buckets for DefenseClaw production')
    ).toHaveCount(0);
  });

  test('renders a useful empty state when no users exist', async ({ page }) => {
    await setupAdminPage(page, { users: [], apiKeys: {}, grants: {} });
    await page.goto('/admin/access');

    await expect(page.getByText('No users yet')).toBeVisible();
    await expect(
      page.getByText(
        'Create the first member, then generate an API key for their SDK and monitor access.'
      )
    ).toBeVisible();
  });

  test('hides admin navigation and denies direct access to members', async ({
    page,
  }) => {
    await mockApiRoutesWithAuthRequired(page, {
      has_active_session: true,
      is_admin: false,
    });

    let accessRequests = 0;
    await page.route('**/api/v1/admin/access/**', async (route) => {
      accessRequests += 1;
      await fulfillJson(route, { detail: 'Forbidden' }, 403);
    });

    await page.goto('/admin/access');

    await expect(page.getByText('Administrator access required')).toBeVisible();
    await expect(
      page.getByRole('link', { name: 'Access management' })
    ).toHaveCount(0);
    expect(accessRequests).toBe(0);
  });

  test('shows a retryable error without exposing stale users', async ({
    page,
  }) => {
    await mockApiRoutesWithAuthRequired(page, {
      has_active_session: true,
      is_admin: true,
    });
    await page.route('**/api/v1/admin/access/users', async (route) => {
      await fulfillJson(route, { detail: 'Database unavailable' }, 503);
    });

    await page.goto('/admin/access');

    await expect(page.getByText('Unable to load users')).toBeVisible();
    await expect(page.getByTestId('retry-access-users')).toBeVisible();
    await expect(page.getByText('DefenseClaw operator')).toHaveCount(0);
  });
});
