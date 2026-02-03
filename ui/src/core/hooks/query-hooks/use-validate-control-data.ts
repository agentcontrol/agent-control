import { useMutation } from "@tanstack/react-query";

import { api } from "@/core/api/client";
import { parseApiError } from "@/core/api/errors";
import type { ControlDefinition } from "@/core/api/types";

/**
 * Mutation hook to validate a control definition without saving it.
 */
export function useValidateControlData() {
  return useMutation({
    mutationFn: async (definition: ControlDefinition) => {
      const { data, error, response } = await api.controls.validateData({
        data: definition,
      });

      if (error) {
        throw parseApiError(
          error,
          "Failed to validate control configuration",
          response?.status
        );
      }

      return data;
    },
  });
}
