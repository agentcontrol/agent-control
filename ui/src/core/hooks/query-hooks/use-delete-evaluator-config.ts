import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/core/api/client";

export function useDeleteEvaluatorConfig() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (configId: number) => {
      const { error } = await api.evaluatorConfigs.delete(configId);
      if (error) throw error;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["evaluator-configs"] });
    },
  });
}
