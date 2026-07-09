import { useMutation, useQueryClient } from '@tanstack/react-query';

import { accessApi } from '@/core/api/access';

import { accessQueryKeys } from './query-keys';

type RevokeApiKeyVariables = {
  userId: string;
};

export function useRevokeApiKey() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ userId }: RevokeApiKeyVariables) => {
      const { error } = await accessApi.credentials.revoke(userId);
      if (error) {
        throw new Error('Failed to revoke API key');
      }
    },
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({
        queryKey: accessQueryKeys.apiKeys(variables.userId),
      });
    },
  });
}
