import { useQuery } from '@tanstack/react-query';

import { accessApi } from '@/core/api/access';

import { accessQueryKeys } from './query-keys';

export function useApiKeyControlGrants(apiKeyId: string, enabled = true) {
  return useQuery({
    queryKey: accessQueryKeys.controlGrants(apiKeyId),
    enabled,
    queryFn: async () => {
      const { data, error } =
        await accessApi.apiKeys.getControlGrants(apiKeyId);
      if (error || !data) {
        throw new Error('Failed to load control grants');
      }
      return data;
    },
  });
}
