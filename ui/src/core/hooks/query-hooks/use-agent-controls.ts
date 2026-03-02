import { useQuery } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import type {
  AgentControlsResponse,
  GetAgentControlsPathParams,
} from '@/core/api/types';

/**
 * Query hook to fetch active controls for an agent
 *
 * @param agentName - Immutable agent name (required)
 */
export function useAgentControls(
  agentName: GetAgentControlsPathParams['agent_name']
) {
  return useQuery<AgentControlsResponse>({
    queryKey: ['agent', agentName, 'controls'],
    queryFn: async () => {
      const { data, error } = await api.agents.getControls(agentName);
      if (error) throw error;
      return data;
    },
  });
}
