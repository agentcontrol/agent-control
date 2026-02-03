import type { TimeRangeValue } from "@rungalileo/jupiter-ds";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/core/api/client";
import type { TimeRange } from "@/core/hooks/query-hooks/use-agent-monitor";
import { mapTimeRangeTypeToTimeRange } from "@/core/page-components/agent-detail/monitor/utils";

const TIME_RANGE_STORAGE_KEY = "agent-control-time-range-preference";

/**
 * Get stored time range from localStorage, defaulting to "7d"
 */
function getStoredTimeRange(): TimeRange {
  if (typeof window === "undefined") return "7d";
  
  try {
    const stored = localStorage.getItem(TIME_RANGE_STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored) as TimeRangeValue;
      if (parsed && typeof parsed.type === "string") {
        return mapTimeRangeTypeToTimeRange(parsed.type);
      }
    }
  } catch {
    // Ignore parse errors
  }
  return "7d"; // Default
}

/**
 * Lightweight hook to check if an agent has any monitoring data.
 * Used to determine the default tab (monitor vs controls).
 * Does NOT include timeseries data to minimize payload.
 * Uses the stored time range preference from localStorage.
 */
export function useHasMonitorData(
  agentUuid: string,
  options?: {
    enabled?: boolean;
  }
) {
  return useQuery({
    queryKey: ["has-monitor-data", agentUuid],
    queryFn: async () => {
      const timeRange = getStoredTimeRange();
      
      const { data, error } = await api.observability.getStats({
        agent_uuid: agentUuid,
        time_range: timeRange,
        include_timeseries: false, // Don't need timeseries, just totals
      });

      if (error) {
        return false; // On error, default to no data
      }

      // Check if there's any meaningful data
      const hasData =
        (data.controls && data.controls.length > 0) ||
        (data.totals?.execution_count && data.totals.execution_count > 0);

      return hasData;
    },
    enabled: options?.enabled !== false && !!agentUuid,
    staleTime: 30000, // Consider data fresh for 30 seconds
    refetchOnWindowFocus: false, // Don't refetch on window focus
  });
}
