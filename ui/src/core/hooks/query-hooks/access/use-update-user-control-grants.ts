import { useMutation, useQueryClient } from '@tanstack/react-query';

import { accessApi } from '@/core/api/access';

import { accessQueryKeys } from './query-keys';

type UpdateUserControlGrantsVariables = {
  userId: string;
  controlIds: number[];
};

export function useUpdateUserControlGrants() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      userId,
      controlIds,
    }: UpdateUserControlGrantsVariables) => {
      const { data, error } = await accessApi.grants.update(userId, {
        control_ids: controlIds,
      });
      if (error || !data) {
        throw new Error('Failed to update rule bucket assignments');
      }
      return data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(
        accessQueryKeys.controlGrants(data.user_id),
        data
      );
    },
  });
}
