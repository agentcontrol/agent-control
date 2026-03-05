import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import { parseApiError } from '@/core/api/errors';
import type { ControlDefinition } from '@/core/api/types';

type AddControlToAgentParams = {
  agentId: string;
  controlName: string;
  definition: ControlDefinition;
};

/**
 * Mutation hook to add a control to an agent
 * Flow:
 * 1. Create the control
 * 2. Set control data (definition)
 * 3. Associate the control directly with the agent
 */
export function useAddControlToAgent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      agentId,
      controlName,
      definition,
    }: AddControlToAgentParams) => {
      let createdControlId: number | null = null;

      try {
        // Step 1: Create the control
        const {
          data: createControlResult,
          error: createControlError,
          response: createControlResponse,
        } = await api.controls.create({ name: controlName });

        if (createControlError || !createControlResult) {
          throw parseApiError(
            createControlError,
            'Failed to create control',
            createControlResponse?.status
          );
        }

        createdControlId = createControlResult.control_id;

        // Step 2: Set control data (definition)
        const { error: setDataError, response: setDataResponse } =
          await api.controls.setData(createdControlId, {
            data: definition,
          });

        if (setDataError) {
          throw parseApiError(
            setDataError,
            'Failed to set control data',
            setDataResponse?.status
          );
        }

        // Step 3: Associate control directly with the agent.
        const { error: associateError, response: associateResponse } =
          await api.agents.addControl(agentId, createdControlId);

        if (associateError) {
          throw parseApiError(
            associateError,
            'Failed to add control to agent',
            associateResponse?.status
          );
        }

        return { controlId: createdControlId };
      } catch (error) {
        // Best effort cleanup: avoid orphan controls if a later step fails.
        if (createdControlId !== null) {
          try {
            await api.controls.delete(createdControlId, { force: true });
          } catch {
            // Preserve the original error from the primary flow.
          }
        }
        throw error;
      }
    },
    onSuccess: (_data, variables) => {
      // Invalidate relevant queries to refetch data
      queryClient.invalidateQueries({ queryKey: ['agent', variables.agentId] });
      queryClient.invalidateQueries({
        queryKey: ['agent', variables.agentId, 'controls'],
      });
      queryClient.invalidateQueries({
        queryKey: ['controls', 'infinite'],
      });
      // Invalidate agents list query to refresh active controls count
      queryClient.invalidateQueries({
        queryKey: ['agents', 'infinite'],
      });
    },
  });
}
