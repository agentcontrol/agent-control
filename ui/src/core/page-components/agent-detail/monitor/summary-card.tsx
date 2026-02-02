"use client";

import {
  Badge,
  Box,
  Card,
  Group,
  Progress,
  RingProgress,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconCheck,
  IconX,
} from "@tabler/icons-react";

import type { SummaryMetrics } from "./types";

interface SummaryCardProps {
  summary: SummaryMetrics;
}

export function SummaryCard({ summary }: SummaryCardProps) {
  return (
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
                          summary.actionCounts?.allow !== undefined
                            ? (summary.actionCounts.allow / summary.totalMatches) * 100
                            : 0,
                        color: "var(--mantine-color-green-4)",
                        tooltip: `Allow: ${summary.actionCounts?.allow || 0}`,
                      },
                      {
                        value:
                          summary.actionCounts?.deny !== undefined
                            ? (summary.actionCounts.deny / summary.totalMatches) * 100
                            : 0,
                        color: "var(--mantine-color-red-4)",
                        tooltip: `Deny: ${summary.actionCounts?.deny || 0}`,
                      },
                      {
                        value:
                          summary.actionCounts?.warn !== undefined
                            ? (summary.actionCounts.warn / summary.totalMatches) * 100
                            : 0,
                        color: "var(--mantine-color-yellow-4)",
                        tooltip: `Warn: ${summary.actionCounts?.warn || 0}`,
                      },
                      {
                        value:
                          summary.actionCounts?.log !== undefined
                            ? (summary.actionCounts.log / summary.totalMatches) * 100
                            : 0,
                        color: "var(--mantine-color-blue-4)",
                        tooltip: `Log: ${summary.actionCounts?.log || 0}`,
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
                          {summary.actionCounts?.allow !== undefined && (
                            <Group justify="space-between" gap="xs" p={8}>
                              <Group gap="sm">
                                <Box
                                  w={14}
                                  h={14}
                                  style={{
                                    borderRadius: 3,
                                    backgroundColor: "var(--mantine-color-green-4)",
                                  }}
                                />
                                <Text size="sm" fw={600}>
                                  Allow
                                </Text>
                              </Group>
                              <Group gap={6}>
                                <Text size="sm" fw={700} style={{ color: "var(--mantine-color-green-6)" }}>
                                  {summary.actionCounts.allow}
                                </Text>
                                <Text size="sm" fw={500} c="dimmed">
                                  ({((summary.actionCounts.allow / summary.totalMatches) * 100).toFixed(1)}%)
                                </Text>
                              </Group>
                            </Group>
                          )}
                          {summary.actionCounts?.deny !== undefined && (
                            <Group justify="space-between" gap="xs" p={8}>
                              <Group gap="sm">
                                <Box
                                  w={14}
                                  h={14}
                                  style={{
                                    borderRadius: 3,
                                    backgroundColor: "var(--mantine-color-red-4)",
                                  }}
                                />
                                <Text size="sm" fw={600}>
                                  Deny
                                </Text>
                              </Group>
                              <Group gap={6}>
                                <Text size="sm" fw={700} style={{ color: "var(--mantine-color-red-6)" }}>
                                  {summary.actionCounts.deny}
                                </Text>
                                <Text size="sm" fw={500} c="dimmed">
                                  ({((summary.actionCounts.deny / summary.totalMatches) * 100).toFixed(1)}%)
                                </Text>
                              </Group>
                            </Group>
                          )}
                          {summary.actionCounts?.warn !== undefined && (
                            <Group justify="space-between" gap="xs" p={8}>
                              <Group gap="sm">
                                <Box
                                  w={14}
                                  h={14}
                                  style={{
                                    borderRadius: 3,
                                    backgroundColor: "var(--mantine-color-yellow-4)",
                                  }}
                                />
                                <Text size="sm" fw={600}>
                                  Warn
                                </Text>
                              </Group>
                              <Group gap={6}>
                                <Text size="sm" fw={700} style={{ color: "var(--mantine-color-yellow-6)" }}>
                                  {summary.actionCounts.warn}
                                </Text>
                                <Text size="sm" fw={500} c="dimmed">
                                  ({((summary.actionCounts.warn / summary.totalMatches) * 100).toFixed(1)}%)
                                </Text>
                              </Group>
                            </Group>
                          )}
                          {summary.actionCounts?.log !== undefined && (
                            <Group justify="space-between" gap="xs" p={8}>
                              <Group gap="sm">
                                <Box
                                  w={14}
                                  h={14}
                                  style={{
                                    borderRadius: 3,
                                    backgroundColor: "var(--mantine-color-blue-4)",
                                  }}
                                />
                                <Text size="sm" fw={600}>
                                  Log
                                </Text>
                              </Group>
                              <Group gap={6}>
                                <Text size="sm" fw={700} style={{ color: "var(--mantine-color-blue-6)" }}>
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
  );
}
