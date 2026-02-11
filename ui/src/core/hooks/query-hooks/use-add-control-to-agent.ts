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
 * Mutation hook to add a control to an agent.
 * Flow:
 * 1. Create the control
 * 2. Set control data (definition)
 * 3. Add control to agent directly
 */
export function useAddControlToAgent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      agentId,
      controlName,
      definition,
    }: AddControlToAgentParams) => {
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

      const controlId = createControlResult.control_id;

      // Step 2: Set control data (definition)
      const { error: setDataError, response: setDataResponse } =
        await api.controls.setData(controlId, {
          data: definition,
        });

      if (setDataError) {
        throw parseApiError(
          setDataError,
          'Failed to set control data',
          setDataResponse?.status
        );
      }

      // Step 3: Add control to agent directly
      const { error: addControlError, response: addControlResponse } =
        await api.agents.addControl(agentId, controlId);

      if (addControlError) {
        throw parseApiError(
          addControlError,
          'Failed to add control to agent',
          addControlResponse?.status
        );
      }

      return { controlId };
    },
    onSuccess: (_data, variables) => {
      // Invalidate relevant queries to refetch data
      queryClient.invalidateQueries({ queryKey: ['controls'] });
      queryClient.invalidateQueries({ queryKey: ['agent', variables.agentId] });
      queryClient.invalidateQueries({
        queryKey: ['agentControls', variables.agentId],
      });
    },
  });
}
