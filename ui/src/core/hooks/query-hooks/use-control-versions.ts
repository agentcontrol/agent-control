import { useInfiniteQuery } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import type { ListControlVersionsResponse } from '@/core/api/types';

import { controlVersionKeys } from './control-version-keys';

const CONTROL_VERSIONS_PAGE_SIZE = 20;

export function useControlVersions(controlId: number) {
  return useInfiniteQuery({
    queryKey: controlVersionKeys.list(controlId),
    queryFn: async ({ pageParam }: { pageParam: number | undefined }) => {
      const { data, error } = await api.controls.listVersions(controlId, {
        cursor: pageParam,
        limit: CONTROL_VERSIONS_PAGE_SIZE,
      });
      if (error) throw error;
      return data;
    },
    getNextPageParam: (lastPage: ListControlVersionsResponse) => {
      if (!lastPage.pagination.has_more || !lastPage.pagination.next_cursor) {
        return undefined;
      }
      return Number(lastPage.pagination.next_cursor);
    },
    initialPageParam: undefined,
  });
}
