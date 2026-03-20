import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import type { ControlDefinition } from '@/core/api/types';

type CreateControlParams = {
  name: string;
  definition: ControlDefinition;
};

/**
 * Mutation hook to create a new control with its definition in one request.
 */
export function useCreateControl() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ name, definition }: CreateControlParams) => {
      // Create and validate the control atomically on the server.
      const { data: createResult, error: createError } =
        await api.controls.create({ name, data: definition });

      if (createError) throw createError;
      if (!createResult) throw new Error('Failed to create control');
      return { controlId: createResult.control_id, success: true };
    },
    onSuccess: () => {
      // Invalidate relevant queries to refetch data
      queryClient.invalidateQueries({ queryKey: ['controls'] });
      queryClient.invalidateQueries({ queryKey: ['agent'] });
    },
  });
}
