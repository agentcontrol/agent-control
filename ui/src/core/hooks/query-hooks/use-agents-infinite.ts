import { useInfiniteQuery } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import type { ListAgentsResponse } from '@/core/api/types';

const AGENTS_PAGE_SIZE = 10;

export type UseAgentsInfiniteParams = {
  name?: string;
  enabled?: boolean;
};

/**
 * Infinite query hook to fetch agents with cursor-based pagination
 * Supports server-side filtering by name
 */
export function useAgentsInfinite(params?: UseAgentsInfiniteParams) {
  const { enabled = true, ...filterParams } = params ?? {};

  return useInfiniteQuery({
    queryKey: ['agents', 'infinite', filterParams],
    queryFn: async ({ pageParam }: { pageParam: string | undefined }) => {
      const { data, error } = await api.agents.list({
        cursor: pageParam,
        limit: AGENTS_PAGE_SIZE,
        ...filterParams,
      });
      if (error) throw error;
      return data;
    },
    getNextPageParam: (lastPage: ListAgentsResponse) => {
      // Return undefined if no more pages (stops infinite query)
      return lastPage.pagination.next_cursor ?? undefined;
    },
    initialPageParam: undefined,
    enabled,
  });
}
