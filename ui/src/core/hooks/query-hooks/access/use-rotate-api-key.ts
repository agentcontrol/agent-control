import { useMutation, useQueryClient } from '@tanstack/react-query';

import { accessApi, type CredentialRequest } from '@/core/api/access';

import { accessQueryKeys } from './query-keys';

type RotateApiKeyVariables = {
  userId: string;
  request?: CredentialRequest;
};

export function useRotateApiKey() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ userId, request = {} }: RotateApiKeyVariables) => {
      const { data, error } = await accessApi.credentials.rotate(
        userId,
        request
      );
      if (error || !data) {
        throw new Error('Failed to rotate API key');
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
