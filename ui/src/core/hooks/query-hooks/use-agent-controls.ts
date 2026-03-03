import { useQuery } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import type {
  AgentControlsResponse,
  GetAgentControlsPathParams,
} from '@/core/api/types';

/**
 * Query hook to fetch active controls for an agent
 *
 * @param agentId - UUID of the agent (required)
 */
export function useAgentControls(
  agentId: GetAgentControlsPathParams['agent_name']
) {
  return useQuery<AgentControlsResponse>({
    queryKey: ['agent', agentId, 'controls'],
    queryFn: async () => {
      const { data, error } = await api.agents.getControls(agentId);
      if (error) throw error;
      return data;
    },
  });
}
