import {
  Alert,
  Badge,
  Box,
  Code,
  Group,
  Paper,
  Stack,
  Table,
  Text,
} from '@mantine/core';

import type { ControlVersionDiffResult } from './diff-control-version';
import { formatDiffValue } from './diff-control-version';

type ControlVersionDiffProps = {
  diff: ControlVersionDiffResult;
  beforeLabel: string;
  afterLabel: string;
  initialVersion?: boolean;
};

export function ControlVersionDiff({
  diff,
  beforeLabel,
  afterLabel,
  initialVersion = false,
}: ControlVersionDiffProps) {
  if (initialVersion) {
    return (
      <Alert color="blue" variant="light" title="Initial version">
        This is the first recorded version for the control, so there is no
        predecessor diff.
      </Alert>
    );
  }

  return (
    <Stack gap="md">
      <Box>
        <Text size="sm" fw={600} mb="xs">
          Change summary
        </Text>
        <Group gap="xs">
          {diff.summary.map((item) => (
            <Badge
              key={item}
              variant="light"
              color={item === 'No changes' ? 'gray' : 'blue'}
            >
              {item}
            </Badge>
          ))}
        </Group>
      </Box>

      <Box>
        <Text size="sm" fw={600} mb="xs">
          Changed paths
        </Text>
        {diff.changes.length === 0 ? (
          <Paper withBorder p="sm" radius="sm">
            <Text size="sm" c="dimmed">
              No saved fields changed in this version.
            </Text>
          </Paper>
        ) : (
          <Table.ScrollContainer minWidth={640}>
            <Table striped highlightOnHover withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Path</Table.Th>
                  <Table.Th>Type</Table.Th>
                  <Table.Th>{beforeLabel}</Table.Th>
                  <Table.Th>{afterLabel}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {diff.changes.map((change) => (
                  <Table.Tr key={change.path}>
                    <Table.Td>
                      <Code>{change.path}</Code>
                    </Table.Td>
                    <Table.Td>
                      <Badge size="sm" variant="light">
                        {change.type}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <ValuePreview value={change.before} />
                    </Table.Td>
                    <Table.Td>
                      <ValuePreview value={change.after} />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Box>

      <details>
        <summary>
          <Text span size="sm" fw={600}>
            Raw JSON
          </Text>
        </summary>
        <Group align="flex-start" grow mt="sm">
          <RawJsonBlock label={beforeLabel} value={diff.before} />
          <RawJsonBlock label={afterLabel} value={diff.after} />
        </Group>
      </details>
    </Stack>
  );
}

function ValuePreview({ value }: { value: unknown }) {
  return (
    <Text size="xs" component="pre" style={{ whiteSpace: 'pre-wrap' }}>
      {formatDiffValue(value)}
    </Text>
  );
}

function RawJsonBlock({
  label,
  value,
}: {
  label: string;
  value: Record<string, unknown>;
}) {
  return (
    <Paper withBorder p="sm" radius="sm">
      <Text size="xs" fw={600} c="dimmed" mb={4}>
        {label}
      </Text>
      <Code block>{JSON.stringify(value, null, 2)}</Code>
    </Paper>
  );
}
