import { useMutation } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import { parseApiError } from '@/core/api/errors';
import type { ControlDefinition } from '@/core/api/types';

export type ValidateControlDataVariables = {
  definition: ControlDefinition;
  signal?: AbortSignal;
};

/**
 * Mutation hook to validate a control definition without saving it.
 * Pass signal to cancel the previous request when starting a new one.
 */
export function useValidateControlData() {
  return useMutation({
    mutationFn: async ({
      definition,
      signal,
    }: ValidateControlDataVariables) => {
      const { data, error, response } = await api.controls.validateData({
        data: definition,
        signal,
      });

      if (error) {
        throw parseApiError(
          error,
          'Failed to validate control configuration',
          response?.status
        );
      }

      return data;
    },
  });
}
