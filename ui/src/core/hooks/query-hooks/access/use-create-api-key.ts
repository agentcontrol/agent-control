import { useMutation, useQueryClient } from '@tanstack/react-query';

import { accessApi, type CreateApiKeyRequest } from '@/core/api/access';

import { accessQueryKeys } from './query-keys';

type CreateApiKeyVariables = {
  userId: string;
  request: CreateApiKeyRequest;
};

export function useCreateApiKey() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ userId, request }: CreateApiKeyVariables) => {
      const { data, error } = await accessApi.apiKeys.create(userId, request);
      if (error || !data) {
        throw new Error('Failed to create API key');
      }
      return data;
    },
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({
        queryKey: accessQueryKeys.apiKeys(variables.userId),
      });
    },
  });
}
