import { api } from './client';
import type { components } from './generated/api-types';

export type AccessUserResponse = components['schemas']['AccessUserResponse'];
export type AccessUserRole = AccessUserResponse['role'];
export type AccessUsersResponse =
  components['schemas']['AccessUserListResponse'];
export type ApiKeyResponse = components['schemas']['APIKeyResponse'];
export type ApiKeysResponse = components['schemas']['APIKeyListResponse'];
export type CreateApiKeyResponse =
  components['schemas']['CreateAPIKeyResponse'];
export type ApiKeyControlGrant = components['schemas']['APIKeyGrantResponse'];
export type CreateAccessUserRequest =
  components['schemas']['CreateAccessUserRequest'];
export type UpdateAccessUserRequest =
  components['schemas']['UpdateAccessUserRequest'];
export type CreateApiKeyRequest = components['schemas']['CreateAPIKeyRequest'];
export type UpdateControlGrantsRequest =
  components['schemas']['ReplaceAPIKeyGrantsRequest'];

export const accessApi = api.access;
