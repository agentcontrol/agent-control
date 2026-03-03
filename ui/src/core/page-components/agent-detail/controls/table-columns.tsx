import { ActionIcon, Badge, Box, Group, Switch, Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconPencil, IconTrash } from '@tabler/icons-react';
import { type ColumnDef } from '@tanstack/react-table';
import { useMemo } from 'react';

import type { Control } from '@/core/api/types';
import type { useRemoveControlFromAgent } from '@/core/hooks/query-hooks/use-remove-control-from-agent';
import type { useUpdateControl } from '@/core/hooks/query-hooks/use-update-control';

import { getStepTypeLabelAndColor } from './utils';

type UseControlsTableColumnsParams = {
  agentId: string;
  updateControl: ReturnType<typeof useUpdateControl>;
  removeControlFromAgent: ReturnType<typeof useRemoveControlFromAgent>;
  onEditControl: (control: Control) => void;
  onDeleteControl: (control: Control) => void;
};

export function useControlsTableColumns({
  agentId,
  updateControl,
  removeControlFromAgent,
  onEditControl,
  onDeleteControl,
}: UseControlsTableColumnsParams): ColumnDef<Control>[] {
  return useMemo(
    () => [
      {
        id: 'enabled',
        header: '',
        size: 60,
        cell: ({ row }: { row: { original: Control } }) => {
          const control = row.original;
          const enabled = control.control?.enabled ?? false;
          return (
            <Switch
              checked={enabled}
              color="green.5"
              onChange={(e) => {
                const newEnabled = e.currentTarget.checked;
                modals.openConfirmModal({
                  title: newEnabled ? 'Enable control?' : 'Disable control?',
                  children: (
                    <Text size="sm" c="dimmed">
                      {newEnabled
                        ? `Enable "${control.name}"?`
                        : `Disable "${control.name}"?`}
                    </Text>
                  ),
                  labels: { confirm: 'Confirm', cancel: 'Cancel' },
                  confirmProps: {
                    variant: 'filled',
                    color: 'violet',
                    size: 'sm',
                    className: 'confirm-modal-confirm-btn',
                  },
                  cancelProps: { variant: 'default', size: 'sm' },
                  onConfirm: () =>
                    updateControl.mutate(
                      {
                        agentId,
                        controlId: control.id,
                        definition: {
                          ...control.control,
                          enabled: newEnabled,
                        },
                      },
                      {
                        onSuccess: () => {
                          notifications.show({
                            title: newEnabled
                              ? 'Control enabled'
                              : 'Control disabled',
                            message: `"${control.name}" has been ${newEnabled ? 'enabled' : 'disabled'}.`,
                            color: 'green',
                          });
                        },
                        onError: (error) => {
                          notifications.show({
                            title: 'Failed to update control',
                            message:
                              error instanceof Error
                                ? error.message
                                : 'An unexpected error occurred',
                            color: 'red',
                          });
                        },
                      }
                    ),
                });
              }}
            />
          );
        },
      },
      {
        id: 'name',
        header: 'Control',
        accessorKey: 'name',
        cell: ({ row }: { row: { original: Control } }) => (
          <Text size="sm" fw={500}>
            {row.original.name}
          </Text>
        ),
      },
      {
        id: 'step_types',
        header: 'Step types',
        accessorKey: 'control.scope.step_types',
        size: 180,
        cell: ({ row }: { row: { original: Control } }) => {
          const stepTypes = row.original.control?.scope?.step_types ?? [];
          if (stepTypes.length === 0) {
            return (
              <Badge variant="light" color="gray" size="sm">
                All
              </Badge>
            );
          }
          return (
            <Group gap={4} wrap="nowrap">
              {stepTypes.map((stepType: string) => {
                const { label, color } = getStepTypeLabelAndColor(stepType);
                return (
                  <Badge key={stepType} variant="light" color={color} size="sm">
                    {label}
                  </Badge>
                );
              })}
            </Group>
          );
        },
      },
      {
        id: 'stages',
        header: 'Stages',
        accessorKey: 'control.scope.stages',
        size: 120,
        cell: ({ row }: { row: { original: Control } }) => {
          const stages = row.original.control?.scope?.stages ?? [];
          if (stages.length === 0) {
            return (
              <Badge variant="light" color="gray" size="sm">
                All
              </Badge>
            );
          }
          if (stages.length > 1) {
            return (
              <Badge variant="light" color="gray" size="sm">
                Pre/Post
              </Badge>
            );
          }
          const stage = stages[0];
          const label = stage === 'pre' ? 'Pre' : 'Post';
          const color = stage === 'pre' ? 'violet' : 'orange';
          return (
            <Badge variant="light" color={color} size="sm">
              {label}
            </Badge>
          );
        },
      },
      {
        id: 'edit',
        header: '',
        size: 44,
        cell: ({ row }: { row: { original: Control } }) => (
          <Box style={{ display: 'flex', justifyContent: 'center' }}>
            <ActionIcon
              variant="subtle"
              color="gray"
              size="sm"
              onClick={() => onEditControl(row.original)}
              aria-label="Edit control"
            >
              <IconPencil size={16} />
            </ActionIcon>
          </Box>
        ),
      },
      {
        id: 'delete',
        header: '',
        size: 44,
        cell: ({ row }: { row: { original: Control } }) => {
          const control = row.original;
          const isDeleting =
            removeControlFromAgent.isPending &&
            removeControlFromAgent.variables?.controlId === control.id;
          return (
            <Box style={{ display: 'flex', justifyContent: 'center' }}>
              <ActionIcon
                variant="subtle"
                color="red"
                size="sm"
                onClick={() => onDeleteControl(control)}
                aria-label="Remove control from agent"
                disabled={isDeleting}
              >
                <IconTrash size={16} />
              </ActionIcon>
            </Box>
          );
        },
      },
    ],
    [
      agentId,
      updateControl,
      removeControlFromAgent.isPending,
      removeControlFromAgent.variables?.controlId,
      onEditControl,
      onDeleteControl,
    ]
  );
}
