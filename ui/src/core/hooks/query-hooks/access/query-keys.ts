export const accessQueryKeys = {
  users: ['admin-access', 'users'] as const,
  apiKeys: (userId: string) =>
    ['admin-access', 'users', userId, 'api-keys'] as const,
  controlGrants: (userId: string) =>
    ['admin-access', 'users', userId, 'control-grants'] as const,
};
