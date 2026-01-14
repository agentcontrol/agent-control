import { useQuery } from "@tanstack/react-query";

import { api } from "@/core/api/client";
import type { PluginsResponse } from "@/core/api/types";

/**
 * Query hook to fetch available evaluator plugins
 * Returns a dictionary of plugin name to plugin info
 */
export function usePlugins() {
  return useQuery<PluginsResponse>({
    queryKey: ["plugins"],
    queryFn: async () => {
      const { data, error } = await api.plugins.list();
      if (error) throw error;
      return data!;
    },
  });
}
