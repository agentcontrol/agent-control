import createClient from 'openapi-fetch';

import { API_URL, notifyUnauthorized } from './client';

export type AccessUserRole = 'admin' | 'member';

export type AccessUserResponse = {
  id: string;
  name: string;
  role: AccessUserRole;
  enabled: boolean;
  created_at: string;
};

export type AccessUsersResponse = {
  users: AccessUserResponse[];
};

export type ApiKeyResponse = {
  id: string;
  user_id: string;
  name: string;
  key_prefix: string;
  enabled: boolean;
  expires_at?: string | null;
  revoked_at?: string | null;
  created_at: string;
};

export type ApiKeysResponse = {
  api_keys: ApiKeyResponse[];
};

export type CreateApiKeyResponse = {
  api_key: ApiKeyResponse;
  secret: string;
};

export type ApiKeyControlGrant = {
  api_key_id: string;
  control_ids: number[];
};

export type CreateAccessUserRequest = {
  name: string;
  role: AccessUserRole;
};

export type UpdateAccessUserRequest = {
  name?: string;
  role?: AccessUserRole;
  enabled?: boolean;
};

export type CreateApiKeyRequest = {
  name: string;
  expires_at?: string | null;
};

export type UpdateControlGrantsRequest = {
  control_ids: number[];
};

type PathParameters<TPath = never> = {
  query?: never;
  header?: never;
  path?: TPath;
  cookie?: never;
};

type JsonResponse<T> = {
  headers: Record<string, unknown>;
  content: {
    'application/json': T;
  };
};

type EmptyResponse = {
  headers: Record<string, unknown>;
  content?: never;
};

type Operation<TResponse, TBody = never, TPath = never> = {
  parameters: PathParameters<TPath>;
  requestBody?: [TBody] extends [never]
    ? never
    : {
        content: {
          'application/json': TBody;
        };
      };
  responses: {
    200: JsonResponse<TResponse>;
  };
};

type CreatedOperation<TResponse, TBody, TPath = never> = Omit<
  Operation<TResponse, TBody, TPath>,
  'responses'
> & {
  responses: {
    201: JsonResponse<TResponse>;
  };
};

/**
 * Temporary hand-written OpenAPI slice for access management.
 *
 * Replace this interface with paths from generated/api-types.ts after the
 * access-management backend is present in the server OpenAPI document.
 */
export type AccessApiPaths = {
  '/api/v1/admin/access/users': {
    parameters: PathParameters;
    get: Operation<AccessUsersResponse>;
    post: CreatedOperation<AccessUserResponse, CreateAccessUserRequest>;
  };
  '/api/v1/admin/access/users/{user_id}': {
    parameters: PathParameters<{ user_id: string }>;
    patch: Operation<
      AccessUserResponse,
      UpdateAccessUserRequest,
      { user_id: string }
    >;
  };
  '/api/v1/admin/access/users/{user_id}/api-keys': {
    parameters: PathParameters<{ user_id: string }>;
    get: Operation<ApiKeysResponse, never, { user_id: string }>;
    post: CreatedOperation<
      CreateApiKeyResponse,
      CreateApiKeyRequest,
      { user_id: string }
    >;
  };
  '/api/v1/admin/access/api-keys/{api_key_id}': {
    parameters: PathParameters<{ api_key_id: string }>;
    delete: {
      parameters: PathParameters<{ api_key_id: string }>;
      requestBody?: never;
      responses: {
        204: EmptyResponse;
      };
    };
  };
  '/api/v1/admin/access/api-keys/{api_key_id}/control-grants': {
    parameters: PathParameters<{ api_key_id: string }>;
    get: Operation<ApiKeyControlGrant, never, { api_key_id: string }>;
    put: Operation<
      ApiKeyControlGrant,
      UpdateControlGrantsRequest,
      { api_key_id: string }
    >;
  };
};

const accessClient = createClient<AccessApiPaths>({
  baseUrl: API_URL,
  credentials: 'include',
  headers: {
    'Content-Type': 'application/json',
  },
});

accessClient.use({
  async onResponse({ response }) {
    if (response.status === 401) {
      notifyUnauthorized();
    }
    return response;
  },
});

export const accessApi = {
  users: {
    list: () => accessClient.GET('/api/v1/admin/access/users'),
    create: (body: CreateAccessUserRequest) =>
      accessClient.POST('/api/v1/admin/access/users', { body }),
    update: (userId: string, body: UpdateAccessUserRequest) =>
      accessClient.PATCH('/api/v1/admin/access/users/{user_id}', {
        params: { path: { user_id: userId } },
        body,
      }),
  },
  apiKeys: {
    list: (userId: string) =>
      accessClient.GET('/api/v1/admin/access/users/{user_id}/api-keys', {
        params: { path: { user_id: userId } },
      }),
    create: (userId: string, body: CreateApiKeyRequest) =>
      accessClient.POST('/api/v1/admin/access/users/{user_id}/api-keys', {
        params: { path: { user_id: userId } },
        body,
      }),
    revoke: (apiKeyId: string) =>
      accessClient.DELETE('/api/v1/admin/access/api-keys/{api_key_id}', {
        params: { path: { api_key_id: apiKeyId } },
      }),
    getControlGrants: (apiKeyId: string) =>
      accessClient.GET(
        '/api/v1/admin/access/api-keys/{api_key_id}/control-grants',
        { params: { path: { api_key_id: apiKeyId } } }
      ),
    updateControlGrants: (apiKeyId: string, body: UpdateControlGrantsRequest) =>
      accessClient.PUT(
        '/api/v1/admin/access/api-keys/{api_key_id}/control-grants',
        {
          params: { path: { api_key_id: apiKeyId } },
          body,
        }
      ),
  },
};
