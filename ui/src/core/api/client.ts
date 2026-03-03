import createClient from 'openapi-fetch';

import type { paths } from './generated/api-types';
import type {
  CreateControlRequest,
  GetAgentControlsPathParams,
  GetAgentPathParams,
  InitAgentRequestBody,
  ListAgentsQueryParams,
  SetControlDataRequest,
  ValidateControlDataRequest,
  ValidateControlDataResponse,
} from './types';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const apiClient = createClient<paths>({
  baseUrl: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add request/response interceptors if needed
apiClient.use({
  async onRequest({ request }) {
    // Add authentication token if available
    const token = getAuthToken();
    if (token) {
      request.headers.set('Authorization', `Bearer ${token}`);
    }
    return request;
  },
  async onResponse({ response }) {
    // Handle 401 responses globally
    if (response.status === 401) {
      // Handle unauthorized - redirect to login or refresh token
      console.warn('Unauthorized request detected');
    }
    return response;
  },
});

// Helper to get auth token (implement based on your auth strategy)
function getAuthToken(): string | null {
  // For now, return null. Implement token retrieval logic here
  // e.g., from localStorage, cookies, or session
  return null;
}

// Typed API methods
export const api = {
  agents: {
    list: (params?: ListAgentsQueryParams) =>
      apiClient.GET('/api/v1/agents', {
        params: { query: params },
      }),
    get: (agentName: GetAgentPathParams['agent_name']) =>
      apiClient.GET('/api/v1/agents/{agent_name}', {
        params: { path: { agent_name: agentName } },
      }),
    initAgent: (data: InitAgentRequestBody) =>
      apiClient.POST('/api/v1/agents/initAgent', { body: data }),
    getControls: (agentName: GetAgentControlsPathParams['agent_name']) =>
      apiClient.GET('/api/v1/agents/{agent_name}/controls', {
        params: { path: { agent_name: agentName } },
      }),
    getPolicies: (agentName: GetAgentPathParams['agent_name']) =>
      apiClient.GET('/api/v1/agents/{agent_name}/policies', {
        params: { path: { agent_name: agentName } },
      }),
    addPolicy: (
      agentName: GetAgentPathParams['agent_name'],
      policyId: number
    ) =>
      apiClient.POST('/api/v1/agents/{agent_name}/policies/{policy_id}', {
        params: { path: { agent_name: agentName, policy_id: policyId } },
      }),
    removePolicy: (
      agentName: GetAgentPathParams['agent_name'],
      policyId: number
    ) =>
      apiClient.DELETE('/api/v1/agents/{agent_name}/policies/{policy_id}', {
        params: { path: { agent_name: agentName, policy_id: policyId } },
      }),
    clearPolicies: (agentName: GetAgentPathParams['agent_name']) =>
      apiClient.DELETE('/api/v1/agents/{agent_name}/policies', {
        params: { path: { agent_name: agentName } },
      }),
    addControl: (
      agentName: GetAgentPathParams['agent_name'],
      controlId: number
    ) =>
      apiClient.POST('/api/v1/agents/{agent_name}/controls/{control_id}', {
        params: { path: { agent_name: agentName, control_id: controlId } },
      }),
    removeControl: (
      agentName: GetAgentPathParams['agent_name'],
      controlId: number
    ) =>
      apiClient.DELETE('/api/v1/agents/{agent_name}/controls/{control_id}', {
        params: { path: { agent_name: agentName, control_id: controlId } },
      }),
  },
  evaluators: {
    list: () => apiClient.GET('/api/v1/evaluators'),
  },
  controls: {
    list: (params?: {
      cursor?: number;
      limit?: number;
      name?: string;
      enabled?: boolean;
      step_type?: string;
      stage?: string;
      execution?: string;
      tag?: string;
    }) =>
      apiClient.GET('/api/v1/controls', {
        params: params ? { query: params } : undefined,
      }),
    create: (data: CreateControlRequest) =>
      apiClient.PUT('/api/v1/controls', { body: data }),
    getData: (controlId: number) =>
      apiClient.GET('/api/v1/controls/{control_id}/data', {
        params: { path: { control_id: controlId } },
      }),
    setData: (controlId: number, data: SetControlDataRequest) =>
      apiClient.PUT('/api/v1/controls/{control_id}/data', {
        params: { path: { control_id: controlId } },
        body: data,
      }),
    validateData: ({
      data,
      signal,
    }: {
      data: ValidateControlDataRequest['data'];
      signal?: AbortSignal;
    }) =>
      // TODO: remove cast after regenerating api types
      (
        apiClient.POST as unknown as (
          path: '/api/v1/controls/validate',
          init: { body: ValidateControlDataRequest; signal?: AbortSignal }
        ) => Promise<{
          data: ValidateControlDataResponse;
          error?: unknown;
          response?: Response;
        }>
      )('/api/v1/controls/validate', { body: { data }, signal }),
    delete: (controlId: number, options?: { force?: boolean }) =>
      apiClient.DELETE('/api/v1/controls/{control_id}', {
        params: {
          path: { control_id: controlId },
          query:
            options?.force !== undefined ? { force: options.force } : undefined,
        },
      }),
  },
  policies: {
    create: (name: string) =>
      apiClient.PUT('/api/v1/policies', { body: { name } }),
    addControl: (policyId: number, controlId: number) =>
      apiClient.POST('/api/v1/policies/{policy_id}/controls/{control_id}', {
        params: { path: { policy_id: policyId, control_id: controlId } },
      }),
    removeControl: (policyId: number, controlId: number) =>
      apiClient.DELETE('/api/v1/policies/{policy_id}/controls/{control_id}', {
        params: { path: { policy_id: policyId, control_id: controlId } },
      }),
  },
  observability: {
    getStats: (params: {
      agent_name: string;
      time_range?:
        | '1m'
        | '5m'
        | '15m'
        | '1h'
        | '24h'
        | '7d'
        | '30d'
        | '180d'
        | '365d';
      include_timeseries?: boolean;
    }) =>
      apiClient.GET('/api/v1/observability/stats', {
        params: { query: params },
      }),
  },
};
