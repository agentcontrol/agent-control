import { Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';

import type { Control } from '@/core/api/types';
import {
  type RemoveControlFromAgentResult,
  useRemoveControlFromAgent,
} from '@/core/hooks/query-hooks/use-remove-control-from-agent';

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
          the direct association from this agent and does not delete the control
          globally.
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
              // The controls table shows active controls (direct + policy-derived), so
              // remove-direct can legitimately no-op for policy-derived entries.
              if (!result.removed_direct_association) {
                notifications.show({
                  title: 'No direct association found',
                  message: result.control_still_active
                    ? `"${control.name}" is still active for this agent through policy associations.`
                    : `"${control.name}" was not directly associated with this agent.`,
                  color: result.control_still_active ? 'yellow' : 'blue',
                });
                return;
              }

              notifications.show({
                title: 'Control removed',
                message: result.control_still_active
                  ? `"${control.name}" was removed from direct associations, but remains active via policy associations.`
                  : `"${control.name}" has been removed from this agent.`,
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
