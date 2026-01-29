import { useQuery } from "@tanstack/react-query";

import { api } from "@/core/api/client";
import type { components } from "@/core/api/generated/api-types";

export type TimeRange = "1m" | "5m" | "15m" | "1h" | "24h" | "7d";
export type ControlStats = components["schemas"]["ControlStats"];
export type StatsResponse = components["schemas"]["StatsResponse"];

export function useAgentStats(
  agentUuid: string,
  timeRange: TimeRange = "1h",
  options?: {
    enabled?: boolean;
    refetchInterval?: number;
  }
) {
  return useQuery({
    queryKey: ["agent-stats", agentUuid, timeRange],
    queryFn: async (): Promise<StatsResponse> => {
      const { data, error } = await api.observability.getStats({
        agent_uuid: agentUuid,
        time_range: timeRange,
      });

      if (error) {
        throw new Error("Failed to fetch agent stats");
      }

      return data;
    },
    enabled: options?.enabled !== false && !!agentUuid,
    refetchInterval: options?.refetchInterval ?? 5000, // Default 5 seconds
    refetchIntervalInBackground: false, // Pause polling when tab is not visible
  });
}

