import { useQuery } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import type { GetControlVersionResponse } from '@/core/api/types';

import { controlVersionKeys } from './control-version-keys';

export function useControlVersion(
  controlId: number,
  versionNum: number | null | undefined
) {
  return useQuery<GetControlVersionResponse>({
    queryKey:
      versionNum == null
        ? controlVersionKeys.details(controlId)
        : controlVersionKeys.detail(controlId, versionNum),
    queryFn: async () => {
      if (versionNum == null) {
        throw new Error('versionNum is required');
      }
      const { data, error } = await api.controls.getVersion(
        controlId,
        versionNum
      );
      if (error) throw error;
      return data;
    },
    enabled: versionNum != null,
  });
}
