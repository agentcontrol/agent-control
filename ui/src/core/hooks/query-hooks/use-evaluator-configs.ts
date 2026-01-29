import { useQuery } from "@tanstack/react-query";

import { api } from "@/core/api/client";
import type { components } from "@/core/api/generated/api-types";

export type ListEvaluatorConfigsResponse =
  components["schemas"]["ListEvaluatorConfigsResponse"];

export function useEvaluatorConfigs(params?: {
  cursor?: number;
  limit?: number;
  name?: string;
  evaluator?: string;
}) {
  return useQuery<ListEvaluatorConfigsResponse>({
    queryKey: ["evaluator-configs", params],
    queryFn: async () => {
      const { data, error } = await api.evaluatorConfigs.list(params);
      if (error) throw error;
      return data!;
    },
  });
}
