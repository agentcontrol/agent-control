'use client';

import { Badge, Card, Group, Table, Text } from '@mantine/core';
import { DataPill } from '@rungalileo/jupiter-ds';

import type { ControlStats } from '@/core/hooks/query-hooks/use-agent-monitor';

type ControlStatsTableProps = {
  stats: ControlStats[];
};

export function ControlStatsTable({ stats }: ControlStatsTableProps) {
  return (
    <Card withBorder p="md">
      <Table.ScrollContainer minWidth={800}>
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Control</Table.Th>
              <Table.Th>Executions</Table.Th>
              <Table.Th>Triggers</Table.Th>
              <Table.Th>Errors</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {stats.map((control) => {
              const triggerRate =
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
                    <Group gap="xs" wrap="nowrap">
                      <Text size="sm">
                        {control.execution_count.toLocaleString()}
                      </Text>
                      {control.execution_count > 0 && (
                        <DataPill
                          value={`${triggerRate.toFixed(1)}%`}
                          size="sm"
                          variant={
                            triggerRate < 10
                              ? 'positive'
                              : triggerRate <= 20
                                ? 'orange'
                                : 'negative'
                          }
                        />
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" fw={500}>
                      {control.match_count}
                    </Text>
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
