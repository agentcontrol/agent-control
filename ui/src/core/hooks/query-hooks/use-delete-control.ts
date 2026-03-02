import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import { parseApiError } from '@/core/api/errors';

type RemoveControlFromAgentParams = {
  agentId: string;
  controlId: number;
};

export type RemoveControlFromAgentResult = {
  success: boolean;
  removed_from_policy?: boolean;
  no_policy_assigned?: boolean;
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
      const {
        data: policyData,
        error: policyError,
        response: policyResponse,
      } = await api.agents.getPolicy(agentId);

      if (policyResponse?.status === 404) {
        return { success: true, no_policy_assigned: true };
      }

      if (policyError || !policyData) {
        throw parseApiError(
          policyError,
          'Failed to fetch agent policy',
          policyResponse?.status
        );
      }

      const { data, error, response } = await api.policies.removeControl(
        policyData.policy_id,
        controlId
      );

      if (error) {
        throw parseApiError(
          error,
          'Failed to remove control from agent policy',
          response?.status
        );
      }

      return {
        success: data?.success ?? true,
        removed_from_policy: true,
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
