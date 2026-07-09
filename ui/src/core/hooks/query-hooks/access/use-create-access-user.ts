import { useMutation, useQueryClient } from '@tanstack/react-query';

import { accessApi, type CreateAccessUserRequest } from '@/core/api/access';

import { accessQueryKeys } from './query-keys';

export function useCreateAccessUser() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (request: CreateAccessUserRequest) => {
      const { data, error } = await accessApi.users.create(request);
      if (error || !data) {
        throw new Error('Failed to create user');
      }
      return data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: accessQueryKeys.users });
    },
  });
}
