import { Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';

import type { Control } from '@/core/api/types';
import { useDeleteControl } from '@/core/hooks/query-hooks/use-delete-control';

type UseDeleteControlFlowParams = {
  agentId: string;
  selectedControl: Control | null;
  onCloseEditModal: () => void;
};

export function useDeleteControlFlow({
  agentId,
  selectedControl,
  onCloseEditModal,
}: UseDeleteControlFlowParams) {
  const deleteControl = useDeleteControl();

  const handleDeleteControl = (control: Control) => {
    modals.openConfirmModal({
      title: 'Delete control?',
      children: (
        <Text size="sm" c="dimmed">
          Delete &quot;{control.name}&quot;? This will remove the control from
          this agent and delete it. This action cannot be undone.
        </Text>
      ),
      labels: { confirm: 'Delete', cancel: 'Cancel' },
      confirmProps: {
        variant: 'filled',
        color: 'red.7',
        size: 'sm',
      },
      cancelProps: { variant: 'default', size: 'sm' },
      onConfirm: () =>
        deleteControl.mutate(
          {
            agentId,
            controlId: control.id,
            force: true,
          },
          {
            onSuccess: () => {
              notifications.show({
                title: 'Control deleted',
                message: `"${control.name}" has been removed.`,
                color: 'green',
              });
              if (selectedControl?.id === control.id) {
                onCloseEditModal();
              }
            },
            onError: (error) => {
              notifications.show({
                title: 'Failed to delete control',
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
  };

  return { handleDeleteControl, deleteControl };
}
