import { useMutation, useQueryClient } from '@tanstack/react-query';

import { accessApi, type CredentialRequest } from '@/core/api/access';

import { accessQueryKeys } from './query-keys';

type IssueApiKeyVariables = {
  userId: string;
  request?: CredentialRequest;
};

export function useIssueApiKey() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ userId, request = {} }: IssueApiKeyVariables) => {
      const { data, error } = await accessApi.credentials.issue(
        userId,
        request
      );
      if (error || !data) {
        throw new Error('Failed to issue API key');
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
