import { useQuery } from "@tanstack/react-query";

import { api } from "@/core/api/client";
import type { GetAgentPathParams, GetAgentResponse } from "@/core/api/types";

/**
 * Query hook to fetch a single agent by ID
 *
 * @param agentId - UUID of the agent (required)
 *
 */
export function useAgent(agentId: GetAgentPathParams["agent_id"]) {
  return useQuery<GetAgentResponse>({
    queryKey: ["agent", agentId],
    queryFn: async () => {
      const { data, error } = await api.agents.get(agentId);
      if (error) throw error;
      return data;
    },
  });
}
