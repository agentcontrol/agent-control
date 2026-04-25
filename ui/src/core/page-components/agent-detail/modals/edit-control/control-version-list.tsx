import {
  Badge,
  Box,
  Group,
  Paper,
  Stack,
  Text,
  UnstyledButton,
} from '@mantine/core';
import { Button } from '@rungalileo/jupiter-ds';
import { formatDistanceToNow } from 'date-fns';

import type { ControlVersionSummary } from '@/core/api/types';

type ControlVersionListProps = {
  versions: ControlVersionSummary[];
  selectedVersionNum: number | null;
  currentVersionNum: number | null;
  hasMore: boolean;
  isFetchingMore: boolean;
  onSelect: (versionNum: number) => void;
  onLoadMore: () => void;
};

export function ControlVersionList({
  versions,
  selectedVersionNum,
  currentVersionNum,
  hasMore,
  isFetchingMore,
  onSelect,
  onLoadMore,
}: ControlVersionListProps) {
  return (
    <Stack gap="sm">
      {versions.map((version) => {
        const selected = version.version_num === selectedVersionNum;
        const current = version.version_num === currentVersionNum;

        return (
          <UnstyledButton
            key={version.version_num}
            onClick={() => onSelect(version.version_num)}
            aria-pressed={selected}
            aria-label={`Version ${version.version_num}`}
          >
            <Paper
              withBorder
              radius="sm"
              p="sm"
              bg={selected ? 'blue.0' : undefined}
              style={{
                borderColor: selected
                  ? 'var(--mantine-color-blue-4)'
                  : undefined,
              }}
            >
              <Group justify="space-between" align="flex-start" wrap="nowrap">
                <Box>
                  <Group gap="xs" mb={4}>
                    <Text size="sm" fw={700}>
                      Version {version.version_num}
                    </Text>
                    {current ? (
                      <Badge size="xs" color="green" variant="light">
                        Current
                      </Badge>
                    ) : null}
                  </Group>
                  <Text size="xs" c="dimmed">
                    {formatDistanceToNow(new Date(version.created_at), {
                      addSuffix: true,
                    })}
                  </Text>
                  {version.note ? (
                    <Text size="xs" mt={4}>
                      {version.note}
                    </Text>
                  ) : null}
                </Box>
                <Badge size="xs" variant="light">
                  {version.event_type}
                </Badge>
              </Group>
            </Paper>
          </UnstyledButton>
        );
      })}

      {hasMore ? (
        <Button
          variant="outline"
          size="sm"
          onClick={onLoadMore}
          loading={isFetchingMore}
          data-testid="load-older-versions-button"
        >
          Load older versions
        </Button>
      ) : null}
    </Stack>
  );
}
