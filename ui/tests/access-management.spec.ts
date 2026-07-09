import type { Page } from '@playwright/test';

import type {
  AccessUserControlGrant,
  AccessUserResponse,
  ApiKeyResponse,
  CreateAccessUserRequest,
  CredentialRequest,
  UpdateAccessUserRequest,
  UpdateControlGrantsRequest,
} from '@/core/api/access';

import {
  expect,
  mockApiRoutesWithAuthRequired,
  mockData,
  test,
} from './fixtures';

type AccessMockState = {
  users: AccessUserResponse[];
  apiKeys: Record<string, ApiKeyResponse[]>;
  grants: Record<string, AccessUserControlGrant>;
  nextKey: number;
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
  name: 'DefenseClaw operator access',
  key_prefix: 'ac_live_3f4c',
  enabled: true,
  expires_at: null,
  revoked_at: null,
  created_at: '2026-07-09T12:30:00Z',
};

const adminApiKey: ApiKeyResponse = {
  ...memberApiKey,
  id: 'key-admin',
  user_id: adminUser.id,
  name: 'Platform administrator access',
  key_prefix: 'ac_admin_7d2e',
};

function createAccessMockState(): AccessMockState {
  return {
    users: [memberUser, adminUser],
    apiKeys: {
      [memberUser.id]: [{ ...memberApiKey }],
      [adminUser.id]: [],
    },
    grants: {
      [memberUser.id]: {
        user_id: memberUser.id,
        control_ids: [1],
      },
    },
    nextKey: 1,
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

function createKey(
  state: AccessMockState,
  user: AccessUserResponse,
  body: CredentialRequest = {}
) {
  const sequence = state.nextKey++;
  const apiKey: ApiKeyResponse = {
    id: `key-${user.id}-${sequence}`,
    user_id: user.id,
    name: body.name ?? `${user.name} access`,
    key_prefix: `ac_new_${sequence}`,
    enabled: true,
    expires_at: body.expires_at ?? null,
    revoked_at: null,
    created_at: `2026-07-09T13:${String(sequence).padStart(2, '0')}:00Z`,
  };
  state.apiKeys[user.id] = [apiKey, ...(state.apiKeys[user.id] ?? [])];
  return {
    api_key: apiKey,
    secret: `ac_test_generated_secret_${sequence}`,
  };
}

function revokeCurrentKey(state: AccessMockState, userId: string) {
  const current = (state.apiKeys[userId] ?? []).find(
    (key) => key.enabled && !key.revoked_at
  );
  if (current) {
    current.enabled = false;
    current.revoked_at = '2026-07-09T13:10:00Z';
  }
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
        const user: AccessUserResponse = {
          id: `user-${state.users.length + 1}`,
          name: body.name,
          role: body.role,
          enabled: body.enabled,
          created_at: '2026-07-09T13:00:00Z',
        };
        state.users = [...state.users, user];
        state.apiKeys[user.id] = [];
        state.grants[user.id] = { user_id: user.id, control_ids: [] };
        const created = createKey(state, user);
        await fulfillJson(route, { user, ...created }, 201);
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
      if (body.role === 'admin') {
        state.grants[userId] = { user_id: userId, control_ids: [] };
      }
      await fulfillJson(route, user);
      return;
    }

    const keysMatch = path.match(
      /^\/api\/v1\/admin\/access\/users\/([^/]+)\/api-keys$/
    );
    if (keysMatch && method === 'GET') {
      await fulfillJson(route, {
        api_keys: state.apiKeys[keysMatch[1]] ?? [],
      });
      return;
    }

    const rotateMatch = path.match(
      /^\/api\/v1\/admin\/access\/users\/([^/]+)\/api-key\/rotate$/
    );
    if (rotateMatch && method === 'POST') {
      const user = state.users.find(
        (candidate) => candidate.id === rotateMatch[1]
      );
      if (!user) {
        await fulfillJson(route, { detail: 'Not found' }, 404);
        return;
      }
      const body = (await request.postDataJSON()) as CredentialRequest;
      revokeCurrentKey(state, user.id);
      await fulfillJson(route, createKey(state, user, body), 201);
      return;
    }

    const keyMatch = path.match(
      /^\/api\/v1\/admin\/access\/users\/([^/]+)\/api-key$/
    );
    if (keyMatch) {
      const user = state.users.find(
        (candidate) => candidate.id === keyMatch[1]
      );
      if (!user) {
        await fulfillJson(route, { detail: 'Not found' }, 404);
        return;
      }
      if (method === 'DELETE') {
        revokeCurrentKey(state, user.id);
        await route.fulfill({ status: 204 });
        return;
      }
      if (method === 'POST') {
        const body = (await request.postDataJSON()) as CredentialRequest;
        const hasActive = (state.apiKeys[user.id] ?? []).some(
          (key) => key.enabled && !key.revoked_at
        );
        if (hasActive) {
          await fulfillJson(route, { detail: 'Rotate the active key' }, 409);
          return;
        }
        await fulfillJson(route, createKey(state, user, body), 201);
        return;
      }
    }

    const grantMatch = path.match(
      /^\/api\/v1\/admin\/access\/users\/([^/]+)\/control-grants$/
    );
    if (grantMatch) {
      const userId = grantMatch[1];
      if (method === 'GET') {
        await fulfillJson(
          route,
          state.grants[userId] ?? { user_id: userId, control_ids: [] }
        );
        return;
      }
      if (method === 'PUT') {
        const body =
          (await request.postDataJSON()) as UpdateControlGrantsRequest;
        const grant = {
          user_id: userId,
          control_ids: body.control_ids ?? [],
        };
        state.grants[userId] = grant;
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
  test('shows one user credential and user-owned bucket assignments', async ({
    page,
  }) => {
    await setupAdminPage(page);
    await page.goto('/admin/access');

    await expect(page).toHaveURL(/\/admin\/access$/);
    await expect(page).toHaveTitle(/Agent Control/);
    await expect(
      page.getByRole('heading', { name: 'Access management' })
    ).toBeVisible();
    await expect(page.getByText('2 users')).toBeVisible();

    await page.getByRole('button', { name: /DefenseClaw operator/ }).click();
    await expect(page.getByText('Prefix ac_live_3f4c')).toBeVisible();
    await expect(
      page.getByLabel('Assigned rule buckets for DefenseClaw operator')
    ).toBeVisible();
    await expect(
      page.getByText('PII Detection', { exact: true }).first()
    ).toBeVisible();
    await expect(page.getByText(/Create another key/i)).toHaveCount(0);
    await expect(page.getByText('Create API key', { exact: true })).toHaveCount(
      0
    );
  });

  test('loads credential history and user grants only when expanded', async ({
    page,
  }) => {
    await setupAdminPage(page);
    let keyRequests = 0;
    let grantRequests = 0;
    await page.route(
      '**/api/v1/admin/access/users/*/api-keys',
      async (route) => {
        keyRequests += 1;
        await route.fallback();
      }
    );
    await page.route(
      '**/api/v1/admin/access/users/*/control-grants',
      async (route) => {
        grantRequests += 1;
        await route.fallback();
      }
    );

    await page.goto('/admin/access');
    await expect(page.getByText('2 users')).toBeVisible();
    expect(keyRequests).toBe(0);
    expect(grantRequests).toBe(0);

    await page.getByRole('button', { name: /DefenseClaw operator/ }).click();
    await expect.poll(() => keyRequests).toBe(1);
    await expect.poll(() => grantRequests).toBe(1);
  });

  test('loads every paginated rule bucket for assignment', async ({ page }) => {
    await setupAdminPage(page);
    await page.route('**/api/v1/controls?**', async (route, request) => {
      const cursor = new URL(request.url()).searchParams.get('cursor');
      const controls = cursor
        ? [
            {
              ...mockData.controls.controls[0],
              id: 101,
              name: 'Bucket 101',
            },
          ]
        : Array.from({ length: 100 }, (_, index) => ({
            ...mockData.controls.controls[0],
            id: index + 1,
            name: `Bucket ${index + 1}`,
          }));
      await fulfillJson(route, {
        controls,
        pagination: {
          total: 101,
          limit: 100,
          has_more: cursor === null,
          next_cursor: cursor === null ? '100' : null,
        },
      });
    });

    await page.goto('/admin/access');
    await page.getByRole('button', { name: /DefenseClaw operator/ }).click();
    await page
      .getByLabel('Assigned rule buckets for DefenseClaw operator')
      .click();
    await expect(
      page.getByRole('option', { name: 'Bucket 101' })
    ).toBeVisible();
  });

  test('labels administrators as namespace-wide and skips grants', async ({
    page,
  }) => {
    const state = createAccessMockState();
    state.apiKeys[adminUser.id] = [{ ...adminApiKey }];
    await setupAdminPage(page, state);

    await page.goto('/admin/access');
    await page.getByRole('button', { name: /Platform administrator/ }).click();
    await expect(
      page.getByText(
        'Administrators are namespace-wide. Rule bucket assignments do not restrict them.'
      )
    ).toBeVisible();
    await expect(
      page.getByLabel('Assigned rule buckets for Platform administrator')
    ).toHaveCount(0);
  });

  test('shows a disabled user credential as suspended instead of active', async ({
    page,
  }) => {
    const state = createAccessMockState();
    state.users = state.users.map((user) =>
      user.id === memberUser.id ? { ...user, enabled: false } : user
    );
    await setupAdminPage(page, state);

    await page.goto('/admin/access');
    await page.getByRole('button', { name: /DefenseClaw operator/ }).click();

    await expect(page.getByText('Suspended', { exact: true })).toBeVisible();
    await expect(
      page.getByTestId(`rotate-api-key-${memberUser.id}`)
    ).toBeDisabled();
    await expect(
      page.getByTestId(`issue-api-key-${memberUser.id}`)
    ).toHaveCount(0);
  });

  test('creates a user and first key atomically and shows the secret once', async ({
    page,
  }) => {
    const state = await setupAdminPage(page);
    await page.goto('/admin/access');

    await page.getByLabel('Name').fill('Security reviewer');
    await page.getByTestId('create-access-user').click();

    await expect(
      page.getByRole('dialog', { name: 'User and API key created' })
    ).toBeVisible();
    await expect(
      page.getByText('ac_test_generated_secret_1', { exact: true })
    ).toBeVisible();
    await expect(
      page.getByText(/both the UI and DefenseClaw SDK/)
    ).toBeVisible();
    await expect(
      page.getByText('defenseclaw keys set AGENT_CONTROL_API_KEY', {
        exact: true,
      })
    ).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(
      page.getByRole('dialog', { name: 'User and API key created' })
    ).toBeVisible();

    await page.getByTestId('close-api-key-secret').click();
    await expect(
      page.getByText('ac_test_generated_secret_1', { exact: true })
    ).toHaveCount(0);
    expect(state.users.some((user) => user.name === 'Security reviewer')).toBe(
      true
    );
    expect(state.apiKeys['user-3']).toHaveLength(1);
  });

  test('rotation revokes the old key while preserving grants and history', async ({
    page,
  }) => {
    const state = await setupAdminPage(page);
    await page.goto('/admin/access');
    await page.getByRole('button', { name: /DefenseClaw operator/ }).click();

    await page.getByTestId(`rotate-api-key-${memberUser.id}`).click();
    await expect(
      page.getByRole('heading', { name: 'Rotate API key?' })
    ).toBeVisible();
    await page.getByRole('button', { name: 'Rotate key' }).click();

    await expect(
      page.getByRole('dialog', { name: 'API key rotated' })
    ).toBeVisible();
    await page.getByTestId('close-api-key-secret').click();
    await expect(page.getByText('Prefix ac_new_1')).toBeVisible();
    await expect(
      page.getByText('1 previous revoked credential retained for audit.')
    ).toBeVisible();
    expect(state.grants[memberUser.id].control_ids).toEqual([1]);
    expect(state.apiKeys[memberUser.id]).toHaveLength(2);
    expect(state.apiKeys[memberUser.id][1].enabled).toBe(false);
  });

  test('bucket assignments survive revoke and issuing a replacement key', async ({
    page,
  }) => {
    const state = await setupAdminPage(page);
    await page.goto('/admin/access');
    await page.getByRole('button', { name: /DefenseClaw operator/ }).click();

    const grantsInput = page.getByLabel(
      'Assigned rule buckets for DefenseClaw operator'
    );
    await grantsInput.click();
    await page.getByRole('option', { name: 'SQL Injection Guard' }).click();
    await page.getByTestId(`save-grants-${memberUser.id}`).click();
    await expect
      .poll(() => state.grants[memberUser.id].control_ids)
      .toEqual([1, 2]);

    await page.getByTestId(`revoke-api-key-${memberUser.id}`).click();
    await page.getByRole('button', { name: 'Revoke key' }).click();
    await expect(page.getByText('Not active', { exact: true })).toBeVisible();
    await expect(grantsInput).toBeVisible();
    expect(state.grants[memberUser.id].control_ids).toEqual([1, 2]);

    await page.getByTestId(`issue-api-key-${memberUser.id}`).click();
    await expect(
      page.getByRole('dialog', { name: 'API key issued' })
    ).toBeVisible();
    await page.getByTestId('close-api-key-secret').click();
    await expect(page.getByText('Active', { exact: true })).toBeVisible();
    expect(state.grants[memberUser.id].control_ids).toEqual([1, 2]);
  });

  test('renders a useful empty state when no users exist', async ({ page }) => {
    await setupAdminPage(page, {
      users: [],
      apiKeys: {},
      grants: {},
      nextKey: 1,
    });
    await page.goto('/admin/access');

    await expect(page.getByText('No users yet')).toBeVisible();
    await expect(
      page.getByText('Create the first user to issue their UI and SDK key.')
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
