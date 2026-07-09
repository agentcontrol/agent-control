export const accessQueryKeys = {
  users: ['admin-access', 'users'] as const,
  apiKeys: (userId: string) =>
    ['admin-access', 'users', userId, 'api-keys'] as const,
  controlGrants: (apiKeyId: string) =>
    ['admin-access', 'api-keys', apiKeyId, 'control-grants'] as const,
};
