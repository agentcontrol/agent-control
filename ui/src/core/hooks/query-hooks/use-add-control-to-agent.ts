import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/core/api/client";
import type { ControlDefinition } from "@/core/api/types";

interface AddControlToAgentParams {
  agentId: string;
  controlName: string;
  definition: ControlDefinition;
}

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
        const { data: createPolicyResult, error: createPolicyError } =
          await api.policies.create(policyName);

        if (createPolicyError || !createPolicyResult) {
          throw new Error("Failed to create policy");
        }

        policyId = createPolicyResult.policy_id;

        // Assign policy to agent
        const { error: assignError } = await api.agents.setPolicy(
          agentId,
          policyId
        );

        if (assignError) {
          throw new Error("Failed to assign policy to agent");
        }
      } else {
        policyId = policyData.policy_id;
      }

      // Step 3: Create the control
      const { data: createControlResult, error: createControlError } =
        await api.controls.create({ name: controlName });

      if (createControlError || !createControlResult) {
        throw new Error("Failed to create control");
      }

      const controlId = createControlResult.control_id;

      // Step 4: Set control data (definition)
      const { error: setDataError } = await api.controls.setData(controlId, {
        data: definition,
      });

      if (setDataError) {
        throw new Error("Failed to set control data");
      }

      // Step 5: Add control to policy
      const { error: addControlError } = await api.policies.addControl(
        policyId,
        controlId
      );

      if (addControlError) {
        throw new Error("Failed to add control to policy");
      }

      return { controlId, policyId };
    },
    onSuccess: (_data, variables) => {
      // Invalidate relevant queries to refetch data
      queryClient.invalidateQueries({ queryKey: ["controls"] });
      queryClient.invalidateQueries({ queryKey: ["agent", variables.agentId] });
      queryClient.invalidateQueries({
        queryKey: ["agentControls", variables.agentId],
      });
    },
  });
}
