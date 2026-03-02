import { Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';

import type { Control } from '@/core/api/types';
import {
  type RemoveControlFromAgentResult,
  useRemoveControlFromAgent,
} from '@/core/hooks/query-hooks/use-delete-control';

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
  const removeControlFromAgent = useRemoveControlFromAgent();

  const handleDeleteControl = (control: Control) => {
    modals.openConfirmModal({
      title: 'Remove control from agent?',
      children: (
        <Text size="sm" c="dimmed">
          Remove &quot;{control.name}&quot; from this agent? This only removes
          it from the agent&apos;s assigned policy and does not delete the
          control globally.
        </Text>
      ),
      labels: { confirm: 'Remove', cancel: 'Cancel' },
      confirmProps: {
        variant: 'filled',
        color: 'red.7',
        size: 'sm',
      },
      cancelProps: { variant: 'default', size: 'sm' },
      onConfirm: () =>
        removeControlFromAgent.mutate(
          {
            agentId,
            controlId: control.id,
          },
          {
            onSuccess: (result: RemoveControlFromAgentResult) => {
              if (result.no_policy_assigned) {
                notifications.show({
                  title: 'No policy assigned',
                  message: `"${control.name}" was not removed because this agent has no assigned policy.`,
                  color: 'yellow',
                });
                return;
              }

              notifications.show({
                title: 'Control removed',
                message: `"${control.name}" has been removed from this agent policy.`,
                color: 'green',
              });
              if (selectedControl?.id === control.id) {
                onCloseEditModal();
              }
            },
            onError: (error) => {
              notifications.show({
                title: 'Failed to remove control',
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

  return { handleDeleteControl, removeControlFromAgent };
}
