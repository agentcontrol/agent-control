import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/core/api/client";
import type { ControlDefinition } from "@/core/api/types";

interface UpdateControlParams {
  agentId: string;
  controlId: number;
  definition: ControlDefinition;
}

/**
 * Mutation hook to update an existing control's definition
 */
export function useUpdateControl() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ controlId, definition }: UpdateControlParams) => {
      const { data, error } = await api.controls.setData(controlId, {
        data: definition,
      });

      if (error) {
        throw new Error("Failed to update control");
      }

      return data;
    },
    onSuccess: (_data, variables) => {
      // Invalidate agent controls query to refresh the list
      queryClient.invalidateQueries({
        queryKey: ["agent", variables.agentId, "controls"],
      });
    },
  });
}
