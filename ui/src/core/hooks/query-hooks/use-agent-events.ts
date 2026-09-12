import { useQuery } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import type { components } from '@/core/api/generated/api-types';

export type ControlExecutionEvent =
  components['schemas']['ControlExecutionEvent'];
export type EventQueryResponse = components['schemas']['EventQueryResponse'];

export function useAgentEvents(
  agentName: string,
  eventWindowMs: number,
  options?: { enabled?: boolean; refetchInterval?: number }
) {
  return useQuery({
    queryKey: ['agent-monitor-events', agentName, eventWindowMs],
    queryFn: async (): Promise<EventQueryResponse> => {
      const { data, error } = await api.observability.queryEvents({
        agent_name: agentName,
        start_time: new Date(Date.now() - eventWindowMs).toISOString(),
        limit: 20,
        offset: 0,
      });

      if (error) {
        throw new Error('Failed to fetch recent executions');
      }

      return data;
    },
    enabled:
      options?.enabled !== false &&
      !!agentName &&
      Number.isFinite(eventWindowMs) &&
      eventWindowMs > 0,
    refetchInterval: options?.refetchInterval ?? 5000,
    refetchIntervalInBackground: false,
  });
}
