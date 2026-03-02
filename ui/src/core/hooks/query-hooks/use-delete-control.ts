import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import { parseApiError } from '@/core/api/errors';

type RemoveControlFromAgentParams = {
  agentId: string;
  controlId: number;
};

export type RemoveControlFromAgentResult = {
  success: boolean;
  removed_direct_association: boolean;
  control_still_active: boolean;
};

/**
 * Mutation hook to remove a control from a specific agent.
 */
export function useRemoveControlFromAgent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      agentId,
      controlId,
    }: RemoveControlFromAgentParams) => {
      const { data, error, response } = await api.agents.removeControl(
        agentId,
        controlId
      );

      if (error || !data) {
        throw parseApiError(
          error,
          'Failed to remove control from agent',
          response?.status
        );
      }

      return {
        success: data.success,
        removed_direct_association: data.removed_direct_association,
        control_still_active: data.control_still_active,
      } satisfies RemoveControlFromAgentResult;
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ['agent', variables.agentId, 'controls'],
      });
      queryClient.invalidateQueries({
        queryKey: ['controls', 'infinite'],
      });
      queryClient.invalidateQueries({
        queryKey: ['agents', 'infinite'],
      });
    },
  });
}
