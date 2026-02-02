"use client";

import {
  Box,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { TimeRangeSwitch } from "@rungalileo/jupiter-ds";
import {
  IconAlertCircle,
  IconClock,
} from "@tabler/icons-react";
import React, { useMemo, useState } from "react";

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

  const actionCounts = stats.action_counts ?? {};

  return {
    totalExecutions: stats.total_executions,
    totalMatches: stats.total_matches,
    totalNonMatches: stats.total_non_matches,
    totalErrors: stats.total_errors,
    denyRate: stats.total_executions > 0
      ? ((actionCounts.deny || 0) / stats.total_executions) * 100
      : 0,
    matchRate: stats.total_executions > 0
      ? (stats.total_matches / stats.total_executions) * 100
      : 0,
    actionCounts,
  };
}

export function AgentsMonitor({ agentUuid }: AgentsMonitorProps) {
  // Use localStorage preference hook (defaults to 1W)
  const [timeRangeValue, setTimeRangeValue] = useTimeRangePreference();
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  
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

  const isEmpty = !stats || stats.stats.length === 0;

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
          isMenuOpen={isMenuOpen}
          onMenuOpenChange={setIsMenuOpen}
        />
      </Group>

      {/* Empty state */}
      {isEmpty && (
        <Box py="xl">
          <Stack align="center" gap="md">
            <IconClock size={48} color="var(--mantine-color-gray-4)" />
            <Text fw={500} c="dimmed">
              No stats available
            </Text>
            <Text size="sm" c="dimmed">
              Stats will appear here once controls are executed.
            </Text>
          </Stack>
        </Box>
      )}

      {!isEmpty && summary && (
        <>
          <SummaryCard summary={summary} />
          <ControlStatsTable stats={stats.stats} />
        </>
      )}
    </Stack>
  );
}
