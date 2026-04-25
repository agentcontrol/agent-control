import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import { parseApiError } from '@/core/api/errors';
import type {
  AgentControlsResponse,
  Control,
  RestoreControlVersionResponse,
} from '@/core/api/types';

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
      if (!data) {
        throw new Error('Restore response did not include control data');
      }

      return data;
    },
    onSuccess: async (data, variables) => {
      updateRestoredControlCache(queryClient, variables, data);

      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['agent', variables.agentId],
        }),
        queryClient.invalidateQueries({
          queryKey: ['agent', variables.agentId, 'controls'],
        }),
        queryClient.invalidateQueries({ queryKey: ['agents', 'infinite'] }),
        queryClient.invalidateQueries({ queryKey: ['controls'] }),
        queryClient.invalidateQueries({ queryKey: ['controls', 'infinite'] }),
        queryClient.invalidateQueries({
          queryKey: controlVersionKeys.list(variables.controlId),
        }),
        queryClient.invalidateQueries({
          queryKey: controlVersionKeys.details(variables.controlId),
        }),
      ]);
    },
  });
}

function updateRestoredControlCache(
  queryClient: ReturnType<typeof useQueryClient>,
  variables: RestoreControlVersionParams,
  data: RestoreControlVersionResponse
) {
  const restoredControl: Control = {
    id: variables.controlId,
    name: data.name,
    control: data.data,
  };

  queryClient.setQueryData<AgentControlsResponse>(
    ['agent', variables.agentId, 'controls'],
    (current) => {
      if (!current) return current;
      return {
        ...current,
        controls: current.controls.map((control) =>
          control.id === variables.controlId ? restoredControl : control
        ),
      };
    }
  );
}
