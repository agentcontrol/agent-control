import { useInfiniteQuery } from "@tanstack/react-query";

import { api } from "@/core/api/client";
import type { ListAgentsResponse } from "@/core/api/types";

const AGENTS_PAGE_SIZE = 10;

/**
 * Infinite query hook to fetch agents with cursor-based pagination
 * Loads more agents as user scrolls
 */
export function useAgentsInfinite() {
  return useInfiniteQuery({
    queryKey: ["agents", "infinite"],
    queryFn: async ({ pageParam }: { pageParam: string | undefined }) => {
      const { data, error } = await api.agents.list({
        cursor: pageParam,
        limit: AGENTS_PAGE_SIZE,
      });
      if (error) throw error;
      return data;
    },
    getNextPageParam: (lastPage: ListAgentsResponse) => {
      // Return undefined if no more pages (stops infinite query)
      return lastPage.pagination.next_cursor ?? undefined;
    },
    initialPageParam: undefined,
  });
}
