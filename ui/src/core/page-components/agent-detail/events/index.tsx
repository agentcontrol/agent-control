'use client';

import { Box, Loader, Stack, Text } from '@mantine/core';
import type { TimeRangeValue } from '@rungalileo/jupiter-ds';
import { useMemo } from 'react';

import { useAgentEvents } from '@/core/hooks/query-hooks/use-agent-events';

import { RecentExecutions } from '../monitor/recent-executions';
import { mapTimeRangeTypeToTimeRange } from '../monitor/utils';

type AgentEventsProps = {
  agentName: string;
  timeRangeValue: TimeRangeValue;
};

const TIME_RANGE_MILLISECONDS: Record<string, number> = {
  '1m': 60_000,
  '5m': 5 * 60_000,
  '15m': 15 * 60_000,
  '1h': 60 * 60_000,
  '24h': 24 * 60 * 60_000,
  '7d': 7 * 24 * 60 * 60_000,
  '30d': 30 * 24 * 60 * 60_000,
  '180d': 180 * 24 * 60 * 60_000,
  '365d': 365 * 24 * 60 * 60_000,
};

export function AgentEvents({ agentName, timeRangeValue }: AgentEventsProps) {
  const apiTimeRange = useMemo(
    () => mapTimeRangeTypeToTimeRange(timeRangeValue.type),
    [timeRangeValue.type]
  );
  const eventWindowMs =
    TIME_RANGE_MILLISECONDS[apiTimeRange] ?? TIME_RANGE_MILLISECONDS['1h'];
  const {
    data: recentEvents,
    error,
    isLoading,
  } = useAgentEvents(agentName, eventWindowMs, { refetchInterval: 2000 });

  if (isLoading && !recentEvents) {
    return (
      <Box py="xl">
        <Stack align="center" gap="md">
          <Loader size="md" />
          <Text c="dimmed">Loading recent executions...</Text>
        </Stack>
      </Box>
    );
  }

  return (
    <RecentExecutions
      events={recentEvents?.events ?? []}
      hasError={error !== null}
    />
  );
}
