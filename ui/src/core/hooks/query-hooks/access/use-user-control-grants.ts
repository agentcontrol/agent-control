import { useQuery } from '@tanstack/react-query';

import { accessApi } from '@/core/api/access';

import { accessQueryKeys } from './query-keys';

export function useUserControlGrants(userId: string, enabled = true) {
  return useQuery({
    queryKey: accessQueryKeys.controlGrants(userId),
    enabled,
    queryFn: async () => {
      const { data, error } = await accessApi.grants.get(userId);
      if (error || !data) {
        throw new Error('Failed to load control grants');
      }
      return data;
    },
  });
}
