import { useQuery } from '@tanstack/react-query';

import { api } from '@/core/api/client';

export type UseControlsParams = {
  cursor?: number;
  limit?: number;
  name?: string;
  enabled?: boolean;
  step_type?: string;
  stage?: string;
  execution?: string;
  tag?: string;
};

export function useControls(params?: UseControlsParams) {
  return useQuery({
    queryKey: ['controls', 'list', params],
    queryFn: async () => {
      const { data, error } = await api.controls.list(params);
      if (error) {
        throw new Error('Failed to load controls');
      }
      return data;
    },
  });
}

export function useAllControls(
  params?: Omit<UseControlsParams, 'cursor' | 'limit'>
) {
  return useQuery({
    queryKey: ['controls', 'all', params],
    queryFn: async () => {
      const controls = [];
      const seenCursors = new Set<number>();
      let cursor: number | undefined;

      for (;;) {
        const { data, error } = await api.controls.list({
          ...params,
          cursor,
          limit: 100,
        });
        if (error) throw new Error('Failed to load controls');
        controls.push(...data.controls);
        if (!data.pagination.has_more) return controls;

        const nextCursor = Number(data.pagination.next_cursor);
        if (!Number.isSafeInteger(nextCursor) || seenCursors.has(nextCursor)) {
          throw new Error('Invalid controls pagination cursor');
        }
        seenCursors.add(nextCursor);
        cursor = nextCursor;
      }
    },
  });
}
