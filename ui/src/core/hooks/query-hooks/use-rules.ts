import { useQuery } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import type { RulesResponse } from '@/core/api/types';

/**
 * Query hook to fetch available rules.
 * Returns a dictionary of rule name to rule info.
 */
export function useRules() {
  return useQuery<RulesResponse>({
    queryKey: ['rules'],
    queryFn: async () => {
      const { data, error } = await api.rules.list();
      if (error) throw error;
      return data!;
    },
  });
}
