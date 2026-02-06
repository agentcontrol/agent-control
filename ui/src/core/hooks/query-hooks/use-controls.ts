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
