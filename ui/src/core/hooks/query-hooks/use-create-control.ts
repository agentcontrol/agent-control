import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import type { ControlDefinition } from '@/core/api/types';

type CreateControlParams = {
  name: string;
  definition: ControlDefinition;
};

/**
 * Mutation hook to create a new control with its definition
 * 1. Creates the control with a name
 * 2. Sets the control data (definition)
 */
export function useCreateControl() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ name, definition }: CreateControlParams) => {
      // Step 1: Create control with name
      const { data: createResult, error: createError } =
        await api.controls.create({ name });

      if (createError) throw createError;
      if (!createResult) throw new Error('Failed to create control');

      const controlId = createResult.control_id;

      // Step 2: Set control data (definition)
      const { data: setDataResult, error: setDataError } =
        await api.controls.setData(controlId, { data: definition });

      if (setDataError) throw setDataError;

      return { controlId, ...setDataResult };
    },
    onSuccess: () => {
      // Invalidate relevant queries to refetch data
      queryClient.invalidateQueries({ queryKey: ['controls'] });
      queryClient.invalidateQueries({ queryKey: ['agent'] });
    },
  });
}
