import { useQuery } from '@tanstack/react-query';

import { accessApi } from '@/core/api/access';

import { accessQueryKeys } from './query-keys';

export function useAccessUsers(enabled = true) {
  return useQuery({
    queryKey: accessQueryKeys.users,
    enabled,
    queryFn: async () => {
      const { data, error } = await accessApi.users.list();
      if (error || !data) {
        throw new Error('Failed to load access users');
      }
      return data.users;
    },
  });
}
