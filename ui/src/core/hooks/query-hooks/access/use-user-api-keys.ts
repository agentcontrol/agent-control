import { useQuery } from '@tanstack/react-query';

import { accessApi } from '@/core/api/access';

import { accessQueryKeys } from './query-keys';

export function useUserApiKeys(userId: string) {
  return useQuery({
    queryKey: accessQueryKeys.apiKeys(userId),
    queryFn: async () => {
      const { data, error } = await accessApi.apiKeys.list(userId);
      if (error || !data) {
        throw new Error('Failed to load API keys');
      }
      return data.api_keys;
    },
  });
}
