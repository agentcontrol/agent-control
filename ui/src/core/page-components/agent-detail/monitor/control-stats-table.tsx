"use client";

import {
  Badge,
  Box,
  Card,
  Group,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";

import type { ControlStats } from "@/core/hooks/query-hooks/use-agent-monitor";

interface ControlStatsTableProps {
  stats: ControlStats[];
}

export function ControlStatsTable({ stats }: ControlStatsTableProps) {
  return (
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
              <Table.Th>Triggers</Table.Th>
              <Table.Th>Non-Matches</Table.Th>
              <Table.Th>Actions</Table.Th>
              <Table.Th>Errors</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {stats.map((control) => {
              const triggerRate =
                control.execution_count > 0
                  ? (control.match_count / control.execution_count) * 100
                  : 0;

              // Calculate total actions for progress bar
              const totalActions =
                (control.allow_count || 0) +
                (control.deny_count || 0) +
                (control.warn_count || 0) +
                (control.log_count || 0);

              // Calculate percentages for each action type
              const allowPercent =
                totalActions > 0 ? ((control.allow_count || 0) / totalActions) * 100 : 0;
              const denyPercent =
                totalActions > 0 ? ((control.deny_count || 0) / totalActions) * 100 : 0;
              const warnPercent =
                totalActions > 0 ? ((control.warn_count || 0) / totalActions) * 100 : 0;
              const logPercent =
                totalActions > 0 ? ((control.log_count || 0) / totalActions) * 100 : 0;

              return (
                <Table.Tr key={control.control_id}>
                  <Table.Td>
                    <Text fw={500} size="sm">
                      {control.control_name}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs" wrap="nowrap">
                      <Text size="sm">{control.execution_count.toLocaleString()}</Text>
                      {control.execution_count > 0 && (
                        <Text
                          size="sm"
                          fw={600}
                          c={
                            triggerRate < 10
                              ? "var(--mantine-color-green-6)"
                              : triggerRate <= 20
                                ? "var(--mantine-color-yellow-6)"
                                : "var(--mantine-color-red-6)"
                          }
                        >
                          ({triggerRate.toFixed(1)}%)
                        </Text>
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs" wrap="nowrap">
                      <Text size="sm" fw={500}>
                        {control.match_count}
                      </Text>
                      {totalActions > 0 ? (
                        <Tooltip
                          label={
                            <Stack gap={4}>
                              <Text size="xs" fw={600}>Actions Breakdown:</Text>
                              <Text size="xs">Allow: {control.allow_count || 0} ({allowPercent.toFixed(1)}%)</Text>
                              <Text size="xs">Deny: {control.deny_count || 0} ({denyPercent.toFixed(1)}%)</Text>
                              <Text size="xs">Warn: {control.warn_count || 0} ({warnPercent.toFixed(1)}%)</Text>
                              <Text size="xs">Log: {control.log_count || 0} ({logPercent.toFixed(1)}%)</Text>
                              <Text size="xs" c="dimmed" mt={4}>Total: {totalActions}</Text>
                            </Stack>
                          }
                        >
                          <Box w={80} h={6} style={{ borderRadius: 4, overflow: "hidden", display: "flex" }}>
                            {allowPercent > 0 && (
                              <Box
                                style={{
                                  width: `${allowPercent}%`,
                                  backgroundColor: "var(--mantine-color-green-4)",
                                  height: "100%",
                                }}
                              />
                            )}
                            {denyPercent > 0 && (
                              <Box
                                style={{
                                  width: `${denyPercent}%`,
                                  backgroundColor: "var(--mantine-color-red-4)",
                                  height: "100%",
                                }}
                              />
                            )}
                            {warnPercent > 0 && (
                              <Box
                                style={{
                                  width: `${warnPercent}%`,
                                  backgroundColor: "var(--mantine-color-yellow-4)",
                                  height: "100%",
                                }}
                              />
                            )}
                            {logPercent > 0 && (
                              <Box
                                style={{
                                  width: `${logPercent}%`,
                                  backgroundColor: "var(--mantine-color-blue-4)",
                                  height: "100%",
                                }}
                              />
                            )}
                          </Box>
                        </Tooltip>
                      ) : (
                        <Text size="xs" c="dimmed">
                          -
                        </Text>
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" c="dimmed">
                      {control.non_match_count}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {totalActions > 0 ? (
                      <Text size="sm">{totalActions.toLocaleString()}</Text>
                    ) : (
                      <Text size="sm" c="dimmed">
                        -
                      </Text>
                    )}
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
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Card>
  );
}
