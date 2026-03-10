export type AgentDetailTab = 'controls' | 'monitor';

type RouteQueryValue =
  | string
  | number
  | boolean
  | readonly string[]
  | string[]
  | null
  | undefined;

type AgentRouteOptions = {
  tab?: AgentDetailTab;
  query?: Record<string, RouteQueryValue>;
};

export function getAgentRoute(
  agentId: string,
  options?: AgentRouteOptions
): string {
  const params = new URLSearchParams();
  params.set('id', agentId);

  if (options?.tab) {
    params.set('tab', options.tab);
  }

  if (options?.query) {
    for (const [key, value] of Object.entries(options.query)) {
      if (key === 'id' || key === 'tab' || value == null) {
        continue;
      }

      if (Array.isArray(value)) {
        for (const item of value) {
          params.append(key, item);
        }
        continue;
      }

      params.set(key, String(value));
    }
  }

  return `/agents?${params.toString()}`;
}
