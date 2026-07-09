import { useMutation, useQueryClient } from '@tanstack/react-query';

import { accessApi } from '@/core/api/access';

import { accessQueryKeys } from './query-keys';

type UpdateApiKeyControlGrantsVariables = {
  apiKeyId: string;
  controlIds: number[];
};

export function useUpdateApiKeyControlGrants() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      apiKeyId,
      controlIds,
    }: UpdateApiKeyControlGrantsVariables) => {
      const { data, error } = await accessApi.apiKeys.updateControlGrants(
        apiKeyId,
        { control_ids: controlIds }
      );
      if (error || !data) {
        throw new Error('Failed to update rule bucket assignments');
      }
      return data;
    },
    onSuccess: async (data) => {
      queryClient.setQueryData(
        accessQueryKeys.controlGrants(data.api_key_id),
        data
      );
    },
  });
}
