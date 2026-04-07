import { useQuery } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import type { GetControlSchemaResponse } from '@/core/api/types';

export function useControlSchema() {
  return useQuery<GetControlSchemaResponse>({
    queryKey: ['controls', 'schema'],
    queryFn: async () => {
      const { data, error } = await api.controls.getSchema();
      if (error) throw error;
      return data!;
    },
    staleTime: Infinity,
  });
}
