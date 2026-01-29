"use client";

import {
  Badge,
  Box,
  Card,
  Group,
  Loader,
  Progress,
  RingProgress,
  Select,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconCheck,
  IconClock,
  IconX,
} from "@tabler/icons-react";
import React, { useMemo, useState } from "react";

import { type TimeRange,useAgentStats } from "@/core/hooks/query-hooks/use-agent-stats";

interface AgentStatsProps {
  agentUuid: string;
}

export function AgentStats({ agentUuid }: AgentStatsProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>("1h");

  const {
    data: stats,
    isLoading,
    error,
  } = useAgentStats(agentUuid, timeRange, {
    refetchInterval: 5000, // Poll every 5 seconds
  });

  // Calculate summary metrics
  const summary = useMemo(() => {
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
  }, [stats]);

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
        <Select
          label="Time Range"
          value={timeRange}
          onChange={(value) => setTimeRange((value as TimeRange) || "1h")}
          data={[
            { value: "1m", label: "Last 1 minute" },
            { value: "5m", label: "Last 5 minutes" },
            { value: "15m", label: "Last 15 minutes" },
            { value: "1h", label: "Last 1 hour" },
            { value: "24h", label: "Last 24 hours" },
            { value: "7d", label: "Last 7 days" },
          ]}
          w={200}
          size="sm"
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

      {!isEmpty && (
        <>

      {/* Summary Cards - Compact Hierarchical View */}
      {summary && (
        <Card withBorder p="md">
          <Group gap="xl" align="flex-start">
            {/* Left: Total Executions with breakdown */}
            <Stack gap="xs" style={{ flex: 1 }}>
              <Group justify="space-between" align="baseline">
                <Stack gap={2}>
                  <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
                    Total Executions
                  </Text>
                  <Text size="2xl" fw={700}>
                    {summary.totalExecutions.toLocaleString()}
                  </Text>
                </Stack>
                <Stack gap={2} align="flex-end">
                  <Text size="xs" c="dimmed">
                    Match Rate
                  </Text>
                  <Text size="lg" fw={600}>
                    {summary.matchRate.toFixed(1)}%
                  </Text>
                  <Progress
                    value={summary.matchRate}
                    color={summary.matchRate > 10 ? "orange" : "green"}
                    size="xs"
                    w={80}
                  />
                </Stack>
              </Group>

              {/* Compact breakdown */}
              <Group gap="md" mt="sm" pl="xs">
                <Tooltip label="Controls that did not match (passed)">
                  <Group gap={4}>
                    <Badge
                      color="green"
                      variant="light"
                      size="sm"
                      leftSection={<IconCheck size={12} />}
                    >
                      Non-Matches
                    </Badge>
                    <Text size="sm" fw={600} c="green">
                      {summary.totalNonMatches}
                    </Text>
                  </Group>
                </Tooltip>

                <Tooltip label="Controls that matched (triggered)">
                  <Group gap={4}>
                    <Badge
                      color="orange"
                      variant="light"
                      size="sm"
                      leftSection={<IconAlertCircle size={12} />}
                    >
                      Matches
                    </Badge>
                    <Text size="sm" fw={600} c="orange">
                      {summary.totalMatches}
                    </Text>
                  </Group>
                </Tooltip>

                <Tooltip label="Errors during control evaluation">
                  <Group gap={4}>
                    <Badge
                      color="red"
                      variant="light"
                      size="sm"
                      leftSection={<IconX size={12} />}
                    >
                      Errors
                    </Badge>
                    <Text size="sm" fw={600} c={summary.totalErrors > 0 ? "red" : "dimmed"}>
                      {summary.totalErrors}
                    </Text>
                  </Group>
                </Tooltip>
              </Group>
            </Stack>

            {/* Right: Actions breakdown with visual chart */}
            <Box
              pl="md"
              style={{
                borderLeft: "1px solid var(--mantine-color-gray-4)",
                minWidth: 280,
              }}
            >
              <Stack gap="sm">
                <Stack gap={2}>
                  <Text size="sm" tt="uppercase" fw={700}>
                    Actions Distribution
                  </Text>
                  <Text size="sm" c="dimmed" fw={500}>
                    from {summary.totalMatches} matches
                  </Text>
                </Stack>

                {summary.totalMatches > 0 ? (
                  <>
                    {/* Donut Chart */}
                    <Box style={{ position: "relative" }}>
                      <RingProgress
                        size={140}
                        thickness={16}
                        sections={[
                          {
                            value:
                              summary.actionCounts.allow !== undefined
                                ? (summary.actionCounts.allow / summary.totalMatches) * 100
                                : 0,
                            color: "green",
                            tooltip: `Allow: ${summary.actionCounts.allow || 0}`,
                          },
                          {
                            value:
                              summary.actionCounts.deny !== undefined
                                ? (summary.actionCounts.deny / summary.totalMatches) * 100
                                : 0,
                            color: "red",
                            tooltip: `Deny: ${summary.actionCounts.deny || 0}`,
                          },
                          {
                            value:
                              summary.actionCounts.warn !== undefined
                                ? (summary.actionCounts.warn / summary.totalMatches) * 100
                                : 0,
                            color: "yellow",
                            tooltip: `Warn: ${summary.actionCounts.warn || 0}`,
                          },
                          {
                            value:
                              summary.actionCounts.log !== undefined
                                ? (summary.actionCounts.log / summary.totalMatches) * 100
                                : 0,
                            color: "blue",
                            tooltip: `Log: ${summary.actionCounts.log || 0}`,
                          },
                        ]}
                        label={
                          <Text size="xl" ta="center" fw={800} style={{ lineHeight: 1.2 }}>
                            {summary.totalMatches}
                          </Text>
                        }
                      />
                    </Box>

                    {/* Action Legend with percentages */}
                    <Stack gap={6} mt="md">
                      {summary.actionCounts.allow !== undefined && (
                        <Group justify="space-between" gap="xs" p={8}>
                          <Group gap="sm">
                            <Box
                              w={14}
                              h={14}
                              style={{
                                borderRadius: 3,
                                backgroundColor: "var(--mantine-color-green-6)",
                              }}
                            />
                            <Text size="sm" fw={600}>
                              Allow
                            </Text>
                          </Group>
                          <Group gap={6}>
                            <Text size="sm" fw={700} c="green">
                              {summary.actionCounts.allow}
                            </Text>
                            <Text size="sm" fw={500} c="dimmed">
                              ({((summary.actionCounts.allow / summary.totalMatches) * 100).toFixed(1)}%)
                            </Text>
                          </Group>
                        </Group>
                      )}
                      {summary.actionCounts.deny !== undefined && (
                        <Group justify="space-between" gap="xs" p={8}>
                          <Group gap="sm">
                            <Box
                              w={14}
                              h={14}
                              style={{
                                borderRadius: 3,
                                backgroundColor: "var(--mantine-color-red-6)",
                              }}
                            />
                            <Text size="sm" fw={600}>
                              Deny
                            </Text>
                          </Group>
                          <Group gap={6}>
                            <Text size="sm" fw={700} c="red">
                              {summary.actionCounts.deny}
                            </Text>
                            <Text size="sm" fw={500} c="dimmed">
                              ({((summary.actionCounts.deny / summary.totalMatches) * 100).toFixed(1)}%)
                            </Text>
                          </Group>
                        </Group>
                      )}
                      {summary.actionCounts.warn !== undefined && (
                        <Group justify="space-between" gap="xs" p={8}>
                          <Group gap="sm">
                            <Box
                              w={14}
                              h={14}
                              style={{
                                borderRadius: 3,
                                backgroundColor: "var(--mantine-color-yellow-6)",
                              }}
                            />
                            <Text size="sm" fw={600}>
                              Warn
                            </Text>
                          </Group>
                          <Group gap={6}>
                            <Text size="sm" fw={700} c="yellow">
                              {summary.actionCounts.warn}
                            </Text>
                            <Text size="sm" fw={500} c="dimmed">
                              ({((summary.actionCounts.warn / summary.totalMatches) * 100).toFixed(1)}%)
                            </Text>
                          </Group>
                        </Group>
                      )}
                      {summary.actionCounts.log !== undefined && (
                        <Group justify="space-between" gap="xs" p={8}>
                          <Group gap="sm">
                            <Box
                              w={14}
                              h={14}
                              style={{
                                borderRadius: 3,
                                backgroundColor: "var(--mantine-color-blue-6)",
                              }}
                            />
                            <Text size="sm" fw={600}>
                              Log
                            </Text>
                          </Group>
                          <Group gap={6}>
                            <Text size="sm" fw={700} c="blue">
                              {summary.actionCounts.log}
                            </Text>
                            <Text size="sm" fw={500} c="dimmed">
                              ({((summary.actionCounts.log / summary.totalMatches) * 100).toFixed(1)}%)
                            </Text>
                          </Group>
                        </Group>
                      )}
                    </Stack>
                  </>
                ) : (
                  <Box py="md" ta="center">
                    <Text size="sm" c="dimmed">
                      No matches yet
                    </Text>
                  </Box>
                )}
              </Stack>
            </Box>
          </Group>
        </Card>
      )}

      {/* Control Stats Table */}
      <Card withBorder p="md">
        <Title order={4} mb="md" fw={600}>
          Per-Control Statistics
        </Title>
        <Table.ScrollContainer minWidth={800}>
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Control</Table.Th>
                <Table.Th>Executions</Table.Th>
                <Table.Th>Matches</Table.Th>
                <Table.Th>Non-Matches</Table.Th>
                <Table.Th>Actions</Table.Th>
                <Table.Th>Errors</Table.Th>
                <Table.Th>Avg Confidence</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {stats.stats.map((control) => {
                const matchRate =
                  control.execution_count > 0
                    ? (control.match_count / control.execution_count) * 100
                    : 0;

                return (
                  <Table.Tr key={control.control_id}>
                    <Table.Td>
                      <Text fw={500} size="sm">
                        {control.control_name}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{control.execution_count.toLocaleString()}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Tooltip label={`${matchRate.toFixed(1)}% match rate`}>
                        <Group gap="xs">
                          <Text size="sm" c="orange" fw={500}>
                            {control.match_count}
                          </Text>
                          {control.execution_count > 0 && (
                            <Progress
                              value={matchRate}
                              color="orange"
                              size="xs"
                              w={60}
                            />
                          )}
                        </Group>
                      </Tooltip>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" c="dimmed">
                        {control.non_match_count}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Group gap="xs">
                        {control.allow_count > 0 && (
                          <Badge color="green" variant="light" size="sm">
                            Allow: {control.allow_count}
                          </Badge>
                        )}
                        {control.deny_count > 0 && (
                          <Badge color="red" variant="light" size="sm">
                            Deny: {control.deny_count}
                          </Badge>
                        )}
                        {control.warn_count > 0 && (
                          <Badge color="yellow" variant="light" size="sm">
                            Warn: {control.warn_count}
                          </Badge>
                        )}
                        {control.log_count > 0 && (
                          <Badge color="blue" variant="light" size="sm">
                            Log: {control.log_count}
                          </Badge>
                        )}
                        {control.allow_count === 0 &&
                          control.deny_count === 0 &&
                          control.warn_count === 0 &&
                          control.log_count === 0 && (
                            <Text size="xs" c="dimmed">
                              -
                            </Text>
                          )}
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      {control.error_count > 0 ? (
                        <Badge color="red" variant="filled" size="sm">
                          {control.error_count}
                        </Badge>
                      ) : (
                        <Text size="sm" c="dimmed">
                          0
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Tooltip label="Average confidence score">
                        <Badge
                          color={
                            control.avg_confidence >= 0.9
                              ? "green"
                              : control.avg_confidence >= 0.7
                                ? "yellow"
                                : "red"
                          }
                          variant="light"
                          size="sm"
                        >
                          {(control.avg_confidence * 100).toFixed(0)}%
                        </Badge>
                      </Tooltip>
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Card>
      </>
      )}
    </Stack>
  );
}

