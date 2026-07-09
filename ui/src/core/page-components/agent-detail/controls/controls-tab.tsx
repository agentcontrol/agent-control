import { Alert, Center, Loader, Paper, Stack, Text } from '@mantine/core';
import { Button, Table } from '@rungalileo/jupiter-ds';
import { IconAlertCircle, IconEye, IconInbox } from '@tabler/icons-react';
import { type ColumnDef } from '@tanstack/react-table';

import type { Control } from '@/core/api/types';

type ControlsTabProps = {
  controls: Control[];
  controlsLoading: boolean;
  controlsError: Error | null;
  columns: ColumnDef<Control>[];
  canManageControls: boolean;
  onAddControl: () => void;
};

export function ControlsTab({
  controls,
  controlsLoading,
  controlsError,
  columns,
  canManageControls,
  onAddControl,
}: ControlsTabProps) {
  if (controlsLoading) {
    return (
      <Center py="xl">
        <Stack align="center" gap="md">
          <Loader size="md" />
          <Text c="dimmed">Loading controls...</Text>
        </Stack>
      </Center>
    );
  }

  if (controlsError) {
    return (
      <Alert
        icon={<IconAlertCircle size={16} />}
        title="Error loading controls"
        color="red"
      >
        Failed to fetch controls. Please try again later.
      </Alert>
    );
  }

  if (controls.length === 0) {
    return (
      <Paper p="xl" withBorder radius="sm" ta="center">
        <Stack align="center" gap="md" py="xl">
          <IconInbox size={48} color="var(--mantine-color-gray-4)" />
          <Stack gap="xs" align="center">
            <Text fw={500} c="dimmed">
              No controls configured
            </Text>
            <Text size="sm" c="dimmed">
              This agent doesn&apos;t have any controls set up yet.
            </Text>
          </Stack>
          {canManageControls ? (
            <Button
              variant="filled"
              mt="md"
              data-testid="add-control-button"
              onClick={onAddControl}
            >
              Add Control
            </Button>
          ) : null}
        </Stack>
      </Paper>
    );
  }

  return (
    <Stack gap="md">
      {!canManageControls ? (
        <Alert
          icon={<IconEye size={16} />}
          title="Administrator-managed rule buckets"
          color="blue"
          variant="light"
        >
          This API key can view its assigned controls and enforcement history.
          Only an administrator can change rule buckets.
        </Alert>
      ) : null}
      <Table
        columns={columns}
        data={controls}
        maxHeight="calc(100dvh - 270px)"
        highlightOnHover
        withColumnBorders
      />
    </Stack>
  );
}
