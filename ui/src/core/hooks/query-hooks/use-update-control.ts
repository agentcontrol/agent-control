import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import { parseApiError } from '@/core/api/errors';
import type { ControlDefinition } from '@/core/api/types';

import { controlVersionKeys } from './control-version-keys';

type UpdateControlParams = {
  agentId: string;
  controlId: number;
  definition: ControlDefinition;
};

/**
 * Mutation hook to update an existing control's definition
 */
export function useUpdateControl() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ controlId, definition }: UpdateControlParams) => {
      const { data, error, response } = await api.controls.setData(controlId, {
        data: definition,
      });

      if (error) {
        throw parseApiError(
          error,
          'Failed to update control',
          response?.status
        );
      }

      return data;
    },
    onSuccess: async (_data, variables) => {
      // Invalidate agent controls query to refresh the list
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['agent', variables.agentId, 'controls'],
        }),
        // Invalidate agents list query to refresh active controls count
        // (enabled status affects the active_controls_count shown on agents home page)
        queryClient.invalidateQueries({
          queryKey: ['agents', 'infinite'],
        }),
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
