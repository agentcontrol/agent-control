import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import { parseApiError } from '@/core/api/errors';

type DeleteControlParams = {
  agentId: string;
  controlId: number;
  /** If true, dissociate from all policies before deleting. Default true so control can be removed from agent. */
  force?: boolean;
};

/**
 * Mutation hook to delete a control.
 * Use force: true when deleting from agent detail so the control is removed from the policy and then deleted.
 */
export function useDeleteControl() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ controlId, force = true }: DeleteControlParams) => {
      const { data, error, response } = await api.controls.delete(controlId, {
        force,
      });

      if (error) {
        throw parseApiError(
          error,
          'Failed to delete control',
          response?.status
        );
      }

      return data;
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ['agent', variables.agentId, 'controls'],
      });
      queryClient.invalidateQueries({
        queryKey: ['agents', 'infinite'],
      });
    },
  });
}
