import type { TimeRangeType } from "@rungalileo/jupiter-ds";

import type { TimeRange } from "@/core/hooks/query-hooks/use-agent-monitor";

// Map Jupiter DS TimeRangeType to API TimeRange
// API supports: 1m, 5m, 15m, 1h, 24h, 7d, 30d, 180d, 365d
export function mapTimeRangeTypeToTimeRange(type: TimeRangeType): TimeRange {
  const mapping: Record<TimeRangeType, TimeRange> = {
    last5Mins: "5m",
    last15Mins: "15m",
    last30Mins: "1h",      // closest: 1h
    lastHour: "1h",
    last3Hours: "1h",      // closest: 1h (no 3h in API)
    last6Hours: "24h",     // closest: 24h (no 6h in API)
    last12Hours: "24h",
    last24Hours: "24h",
    last2Days: "7d",       // closest: 7d (no 2d in API)
    lastWeek: "7d",
    lastMonth: "30d",
    last6Months: "180d",
    lastYear: "365d",
    custom: "24h",         // Default for custom ranges
  };
  return mapping[type];
}
