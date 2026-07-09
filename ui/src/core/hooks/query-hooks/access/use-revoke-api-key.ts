import { useMutation, useQueryClient } from '@tanstack/react-query';

import { accessApi } from '@/core/api/access';

import { accessQueryKeys } from './query-keys';

type RevokeApiKeyVariables = {
  apiKeyId: string;
  userId: string;
};

export function useRevokeApiKey() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ apiKeyId }: RevokeApiKeyVariables) => {
      const { error } = await accessApi.apiKeys.revoke(apiKeyId);
      if (error) {
        throw new Error('Failed to revoke API key');
      }
    },
    onSuccess: async (_data, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: accessQueryKeys.apiKeys(variables.userId),
        }),
        queryClient.invalidateQueries({
          queryKey: accessQueryKeys.controlGrants(variables.apiKeyId),
        }),
      ]);
    },
  });
}
