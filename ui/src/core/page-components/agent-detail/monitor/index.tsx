"use client";

import {
  Box,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { type TimeRangeOption,TimeRangeSwitch } from "@rungalileo/jupiter-ds";
import { IconAlertCircle } from "@tabler/icons-react";
import React, { useMemo } from "react";

// Custom segment options from 5m to 1Y
const TIME_RANGE_SEGMENTS: TimeRangeOption[] = [
  { label: "5m", value: "last5Mins" },
  { label: "15m", value: "last15Mins" },
  { label: "1H", value: "lastHour" },
  { label: "12H", value: "last12Hours" },
  { label: "1D", value: "last24Hours" },
  { label: "1W", value: "lastWeek" },
  { label: "1M", value: "lastMonth" },
  { label: "1Y", value: "lastYear" },
];

import type { StatsResponse } from "@/core/hooks/query-hooks/use-agent-monitor";
import { useAgentMonitor } from "@/core/hooks/query-hooks/use-agent-monitor";
import { useTimeRangePreference } from "@/core/hooks/use-time-range-preference";

import { ControlStatsTable } from "./control-stats-table";
import { SummaryCard } from "./summary-card";
import type { SummaryMetrics } from "./types";
import { mapTimeRangeTypeToTimeRange } from "./utils";

interface AgentsMonitorProps {
  agentUuid: string;
}

function calculateSummary(stats: StatsResponse | undefined): SummaryMetrics | null {
  if (!stats) return null;

  const actionCounts = stats.totals.action_counts ?? {};

  return {
    totalExecutions: stats.totals.execution_count,
    totalMatches: stats.totals.match_count,
    totalNonMatches: stats.totals.non_match_count,
    totalErrors: stats.totals.error_count,
    denyRate: stats.totals.execution_count > 0
      ? ((actionCounts.deny || 0) / stats.totals.execution_count) * 100
      : 0,
    matchRate: stats.totals.execution_count > 0
      ? (stats.totals.match_count / stats.totals.execution_count) * 100
      : 0,
    actionCounts,
  };
}

export function AgentsMonitor({ agentUuid }: AgentsMonitorProps) {
  // Use localStorage preference hook (defaults to 1W)
  const [timeRangeValue, setTimeRangeValue] = useTimeRangePreference();
  
  // Convert to API TimeRange only when calling the API
  const apiTimeRange = useMemo(
    () => mapTimeRangeTypeToTimeRange(timeRangeValue.type),
    [timeRangeValue.type]
  );

  const {
    data: stats,
    isLoading,
    error,
  } = useAgentMonitor(agentUuid, apiTimeRange, {
    refetchInterval: 5000, // Poll every 5 seconds
    includeTimeseries: true, // Always fetch timeseries for trend chart
  });

  // Calculate summary metrics
  const summary = useMemo(() => calculateSummary(stats), [stats]);

  if (isLoading && !stats) {
    return (
      <Box py="xl">
        <Stack align="center" gap="md">
          <Loader size="md" />
          <Text c="dimmed">Loading stats...</Text>
        </Stack>
      </Box>
    );
  }

  if (error) {
    return (
      <Box py="xl">
        <Stack align="center" gap="md">
          <IconAlertCircle size={48} color="var(--mantine-color-red-6)" />
          <Text c="red" fw={500}>
            Failed to load stats
          </Text>
          <Text size="sm" c="dimmed">
            {error instanceof Error ? error.message : "Unknown error"}
          </Text>
        </Stack>
      </Box>
    );
  }

  // Create empty summary if no data
  const displaySummary = summary || {
    totalExecutions: 0,
    totalMatches: 0,
    totalNonMatches: 0,
    totalErrors: 0,
    denyRate: 0,
    matchRate: 0,
    actionCounts: {},
  };

  return (
    <Stack gap="lg">
      {/* Header with time range selector - always visible */}
      <Group justify="space-between" align="flex-end">
        <Title order={3} fw={600}>
          Control Statistics
        </Title>
        <TimeRangeSwitch
          value={timeRangeValue}
          onChange={setTimeRangeValue}
          segmentOptions={TIME_RANGE_SEGMENTS}
          allowCustomSelection={false}
        />
      </Group>

      {/* Always show the summary card - it handles empty state internally */}
      <SummaryCard 
        summary={displaySummary} 
        timeseries={stats?.totals.timeseries}
        timeRange={apiTimeRange}
      />
      
      {/* Show table only if there's data, otherwise show empty state message */}
      {stats && stats.controls.length > 0 ? (
        <ControlStatsTable stats={stats.controls} />
      ) : (
        <Box py="md" ta="center">
          <Text size="sm" c="dimmed">
            Per-control statistics will appear here once controls are executed.
          </Text>
        </Box>
      )}
    </Stack>
  );
}
