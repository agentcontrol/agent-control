import { useInfiniteQuery } from "@tanstack/react-query";

import { api } from "@/core/api/client";
import type { ListControlsResponse } from "@/core/api/types";

const CONTROLS_PAGE_SIZE = 10;

export interface UseControlsInfiniteParams {
  name?: string;
  enabled?: boolean;
  step_type?: string;
  stage?: string;
  execution?: string;
  tag?: string;
}

/**
 * Infinite query hook to fetch controls with cursor-based pagination
 * Supports server-side filtering by name and other params
 */
export function useControlsInfinite(params?: UseControlsInfiniteParams) {
  const { enabled = true, ...filterParams } = params ?? {};

  return useInfiniteQuery({
    queryKey: ["controls", "infinite", filterParams],
    queryFn: async ({ pageParam }: { pageParam: number | undefined }) => {
      const { data, error } = await api.controls.list({
        cursor: pageParam,
        limit: CONTROLS_PAGE_SIZE,
        ...filterParams,
      });
      if (error) throw error;
      return data;
    },
    getNextPageParam: (lastPage: ListControlsResponse) => {
      // Return undefined if no more pages (stops infinite query)
      if (!lastPage.pagination.has_more) return undefined;
      // Use the last control's ID as cursor for next page
      const controls = lastPage.controls;
      if (controls.length === 0) return undefined;
      return controls[controls.length - 1].id;
    },
    initialPageParam: undefined,
    enabled,
  });
}
