import { useMutation, useQueryClient } from '@tanstack/react-query';

import { accessApi, type UpdateAccessUserRequest } from '@/core/api/access';

import { accessQueryKeys } from './query-keys';

type UpdateAccessUserVariables = {
  userId: string;
  request: UpdateAccessUserRequest;
};

export function useUpdateAccessUser() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ userId, request }: UpdateAccessUserVariables) => {
      const { data, error } = await accessApi.users.update(userId, request);
      if (error || !data) {
        throw new Error('Failed to update user');
      }
      return data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: accessQueryKeys.users });
    },
  });
}
