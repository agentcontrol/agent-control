import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/core/api/client";
import type { components } from "@/core/api/generated/api-types";

export type CreateEvaluatorConfigRequest =
  components["schemas"]["CreateEvaluatorConfigRequest"];
export type EvaluatorConfigItem = components["schemas"]["EvaluatorConfigItem"];

export function useCreateEvaluatorConfig() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (
      data: CreateEvaluatorConfigRequest
    ): Promise<EvaluatorConfigItem> => {
      const { data: result, error } = await api.evaluatorConfigs.create(data);

      if (error) {
        throw error;
      }

      return result;
    },
    onSuccess: () => {
      // Invalidate evaluator configs list if we add that query later
      queryClient.invalidateQueries({ queryKey: ["evaluator-configs"] });
    },
  });
}
