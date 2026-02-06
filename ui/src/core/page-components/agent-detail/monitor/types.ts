import type { StatsTotals } from "@/core/hooks/query-hooks/use-agent-monitor";

export type SummaryMetrics = {
  totalExecutions: number;
  totalMatches: number;
  totalErrors: number;
  denyRate: number;
  actionCounts: NonNullable<StatsTotals["action_counts"]>;
};
