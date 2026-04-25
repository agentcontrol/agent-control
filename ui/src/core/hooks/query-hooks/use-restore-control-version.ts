import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import { parseApiError } from '@/core/api/errors';

import { controlVersionKeys } from './control-version-keys';

type RestoreControlVersionParams = {
  agentId: string;
  controlId: number;
  versionNum: number;
};

export function useRestoreControlVersion() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      controlId,
      versionNum,
    }: RestoreControlVersionParams) => {
      const { data, error, response } = await api.controls.restoreVersion(
        controlId,
        versionNum
      );

      if (error) {
        throw parseApiError(
          error,
          'Failed to restore control version',
          response?.status
        );
      }

      return data;
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['agent', variables.agentId] });
      queryClient.invalidateQueries({
        queryKey: ['agent', variables.agentId, 'controls'],
      });
      queryClient.invalidateQueries({ queryKey: ['agents', 'infinite'] });
      queryClient.invalidateQueries({ queryKey: ['controls'] });
      queryClient.invalidateQueries({ queryKey: ['controls', 'infinite'] });
      queryClient.invalidateQueries({
        queryKey: controlVersionKeys.list(variables.controlId),
      });
      queryClient.invalidateQueries({
        queryKey: controlVersionKeys.details(variables.controlId),
      });
    },
  });
}
