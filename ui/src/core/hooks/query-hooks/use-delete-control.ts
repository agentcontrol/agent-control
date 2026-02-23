import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import { parseApiError } from '@/core/api/errors';

type RemoveControlFromAgentParams = {
  agentId: string;
  controlId: number;
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

      if (error) {
        throw parseApiError(
          error,
          'Failed to remove control from agent',
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
