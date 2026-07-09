import { api } from './client';
import type { components } from './generated/api-types';

export type AccessUserResponse = components['schemas']['AccessUserResponse'];
export type AccessUserRole = AccessUserResponse['role'];
export type AccessUsersResponse =
  components['schemas']['AccessUserListResponse'];
export type ApiKeyResponse = components['schemas']['APIKeyResponse'];
export type ApiKeysResponse = components['schemas']['APIKeyListResponse'];
export type CredentialSecretResponse =
  components['schemas']['CredentialSecretResponse'];
export type CreateAccessUserResponse =
  components['schemas']['CreateAccessUserResponse'];
export type AccessUserControlGrant =
  components['schemas']['AccessUserGrantResponse'];
export type CreateAccessUserRequest =
  components['schemas']['CreateAccessUserRequest'];
export type UpdateAccessUserRequest =
  components['schemas']['UpdateAccessUserRequest'];
export type CredentialRequest = components['schemas']['CredentialRequest'];
export type UpdateControlGrantsRequest =
  components['schemas']['ReplaceAccessUserGrantsRequest'];

export const accessApi = api.access;
