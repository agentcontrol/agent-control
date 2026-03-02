import type { UseQueryOptions, UseQueryResult } from '@tanstack/react-query';
import { useQuery } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import type { GetAgentPathParams, GetAgentResponse } from '@/core/api/types';

/**
 * Query hook to fetch a single agent by identifier.
 *
 * @param agentName - Immutable agent name (required)
 *
 */
export function useAgent(
  agentName: GetAgentPathParams['agent_name'],
  options?: Omit<
    UseQueryOptions<
      GetAgentResponse,
      Error,
      GetAgentResponse,
      readonly unknown[]
    >,
    'queryKey' | 'queryFn'
  >
): UseQueryResult<GetAgentResponse, Error> {
  const { enabled, ...rest } = options ?? {};
  const isEnabled = enabled ?? Boolean(agentName);

  return useQuery({
    queryKey: ['agent', agentName],
    queryFn: async () => {
      const { data, error } = await api.agents.get(agentName);
      if (error) throw error;
      return data;
    },
    enabled: isEnabled,
    ...rest,
  });
}
