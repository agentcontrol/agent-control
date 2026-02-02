import type { StatsResponse } from "@/core/hooks/query-hooks/use-agent-monitor";

export type SummaryMetrics = {
  totalExecutions: number;
  totalMatches: number;
  totalNonMatches: number;
  totalErrors: number;
  denyRate: number;
  matchRate: number;
  actionCounts: StatsResponse["action_counts"];
};
