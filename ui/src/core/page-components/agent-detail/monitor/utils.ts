import type { TimeRangeType } from "@rungalileo/jupiter-ds";

import type { TimeRange } from "@/core/hooks/query-hooks/use-agent-monitor";

// Map Jupiter DS TimeRangeType to our TimeRange
export function mapTimeRangeTypeToTimeRange(type: TimeRangeType): TimeRange {
  const mapping: Record<TimeRangeType, TimeRange> = {
    last5Mins: "5m",
    last15Mins: "15m",
    last30Mins: "15m",
    lastHour: "1h",
    last3Hours: "1h",
    last6Hours: "1h",
    last12Hours: "24h",
    last24Hours: "24h",
    last2Days: "24h",
    lastWeek: "7d",
    lastMonth: "7d",
    last6Months: "7d",
    lastYear: "7d",
    custom: "1h", // Default for custom ranges
  };
  return mapping[type];
}
