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
 * 1. Check if agent has a policy
 * 2. If no policy, create one and assign it to the agent
 * 3. Create the control
 * 4. Set control data (definition)
 * 5. Add control to policy
 */
export function useAddControlToAgent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      agentId,
      controlName,
      definition,
    }: AddControlToAgentParams) => {
      // Step 1: Check if agent has a policy
      let policyId: number;
      const { data: policyData, error: policyError } =
        await api.agents.getPolicy(agentId);

      if (policyError || !policyData?.policy_id) {
        // Step 2: Create a new policy and assign it to the agent
        const policyName = `policy-${agentId}`;
        const {
          data: createPolicyResult,
          error: createPolicyError,
          response: createPolicyResponse,
        } = await api.policies.create(policyName);

        if (createPolicyError || !createPolicyResult) {
          throw parseApiError(
            createPolicyError,
            'Failed to create policy',
            createPolicyResponse?.status
          );
        }

        policyId = createPolicyResult.policy_id;

        // Assign policy to agent
        const { error: assignError, response: assignResponse } =
          await api.agents.setPolicy(agentId, policyId);

        if (assignError) {
          throw parseApiError(
            assignError,
            'Failed to assign policy to agent',
            assignResponse?.status
          );
        }
      } else {
        policyId = policyData.policy_id;
      }

      // Step 3: Create the control
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

      // Step 4: Set control data (definition)
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

      // Step 5: Add control to policy
      const { error: addControlError, response: addControlResponse } =
        await api.policies.addControl(policyId, controlId);

      if (addControlError) {
        throw parseApiError(
          addControlError,
          'Failed to add control to policy',
          addControlResponse?.status
        );
      }

      return { controlId, policyId };
    },
    onSuccess: (_data, variables) => {
      // Invalidate relevant queries to refetch data
      queryClient.invalidateQueries({ queryKey: ['controls'] });
      queryClient.invalidateQueries({ queryKey: ['agent', variables.agentId] });
      queryClient.invalidateQueries({
        queryKey: ['agentControls', variables.agentId],
      });
      // Invalidate agents list query to refresh active controls count
      queryClient.invalidateQueries({
        queryKey: ['agents', 'infinite'],
      });
    },
  });
}
