import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import { parseApiError } from '@/core/api/errors';
import type { ControlDefinition } from '@/core/api/types';

type AddControlToAgentParams = {
  agentId: string;
  controlName: string;
  definition: ControlDefinition;
};

function sanitizePolicyName(agentId: string) {
  return `policy-${agentId}`
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, '-')
    .slice(0, 255);
}

async function ensureAgentPolicy(agentId: string): Promise<number> {
  const {
    data: existingPolicy,
    error: getPolicyError,
    response: getPolicyResponse,
  } = await api.agents.getPolicy(agentId);

  if (!getPolicyError && existingPolicy) {
    return existingPolicy.policy_id;
  }

  if (getPolicyResponse?.status !== 404) {
    throw parseApiError(
      getPolicyError,
      'Failed to fetch agent policy',
      getPolicyResponse?.status
    );
  }

  const policyNameBase = sanitizePolicyName(agentId);
  const policyNameCandidates = [
    policyNameBase,
    `${policyNameBase}-${Date.now()}`,
  ];

  let createdPolicyId: number | null = null;
  for (const candidate of policyNameCandidates) {
    const {
      data: createdPolicy,
      error: createPolicyError,
      response: createPolicyResponse,
    } = await api.policies.create(candidate);

    if (!createPolicyError && createdPolicy) {
      createdPolicyId = createdPolicy.policy_id;
      break;
    }

    if (createPolicyResponse?.status === 409) {
      continue;
    }

    throw parseApiError(
      createPolicyError,
      'Failed to create policy for agent',
      createPolicyResponse?.status
    );
  }

  if (createdPolicyId === null) {
    throw new Error('Unable to create a unique policy for this agent');
  }

  const { error: setPolicyError, response: setPolicyResponse } =
    await api.agents.setPolicy(agentId, createdPolicyId);

  if (setPolicyError) {
    throw parseApiError(
      setPolicyError,
      'Failed to assign policy to agent',
      setPolicyResponse?.status
    );
  }

  return createdPolicyId;
}

/**
 * Mutation hook to add a control to an agent
 * Flow:
 * 1. Create the control
 * 2. Set control data (definition)
 * 3. Ensure the agent has a policy
 * 4. Add the control to that policy
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

        // Step 3: Ensure the agent has a policy.
        const policyId = await ensureAgentPolicy(agentId);

        // Step 4: Add control to policy.
        const { error: associateError, response: associateResponse } =
          await api.policies.addControl(policyId, createdControlId);

        if (associateError) {
          throw parseApiError(
            associateError,
            'Failed to add control to agent policy',
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
      queryClient.invalidateQueries({ queryKey: ['controls'] });
      queryClient.invalidateQueries({ queryKey: ['agent', variables.agentId] });
      queryClient.invalidateQueries({
        queryKey: ['agent', variables.agentId, 'controls'],
      });
      // Invalidate agents list query to refresh active controls count
      queryClient.invalidateQueries({
        queryKey: ['agents', 'infinite'],
      });
    },
  });
}
