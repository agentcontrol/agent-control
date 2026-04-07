import { useMutation } from '@tanstack/react-query';

import { api } from '@/core/api/client';
import { parseApiError } from '@/core/api/errors';
import type { RenderControlTemplateRequest } from '@/core/api/types';

/**
 * Mutation hook to render a control template preview without persisting.
 */
export function useRenderTemplate() {
  return useMutation({
    mutationFn: async (request: RenderControlTemplateRequest) => {
      const { data, error, response } =
        await api.controlTemplates.render(request);

      if (error) {
        throw parseApiError(
          error,
          'Failed to render template',
          response?.status
        );
      }

      return data;
    },
  });
}
