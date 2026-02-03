import { type Page, test as base } from "@playwright/test";

import type {
  AgentControlsResponse,
  AgentSummary,
  Control,
  ControlSummary,
  EvaluatorsResponse,
  GetAgentResponse,
  ListAgentsResponse,
  ListControlsResponse,
} from "@/core/api/types";
import type { StatsResponse } from "@/core/hooks/query-hooks/use-agent-monitor";

/**
 * Mock data for API responses
 * Uses API types to ensure type safety - if backend changes, TypeScript will catch it
 */

// Satisfies ensures type checking while allowing inference of literal types
const agentsList: AgentSummary[] = [
  {
    agent_id: "agent-1",
    agent_name: "Customer Support Bot",
    policy_id: 1,
    created_at: "2024-01-01T00:00:00Z",
    step_count: 5,
    evaluator_count: 2,
    active_controls_count: 3,
  },
  {
    agent_id: "agent-2",
    agent_name: "Data Analysis Agent",
    policy_id: 2,
    created_at: "2024-01-02T00:00:00Z",
    step_count: 3,
    evaluator_count: 1,
    active_controls_count: 2,
  },
  {
    agent_id: "agent-3",
    agent_name: "Code Review Assistant",
    policy_id: 3,
    created_at: "2024-01-03T00:00:00Z",
    step_count: 8,
    evaluator_count: 4,
    active_controls_count: 5,
  },
];

const agentsResponse: ListAgentsResponse = {
  agents: agentsList,
  pagination: {
    total: 3,
    limit: 25,
    has_more: false,
    next_cursor: null,
  },
};

const agentResponse: GetAgentResponse = {
  agent: {
    agent_id: "agent-1",
    agent_name: "Customer Support Bot",
    agent_description: "Handles customer inquiries and support tickets",
    agent_created_at: "2024-01-01T00:00:00Z",
    agent_updated_at: "2024-01-15T00:00:00Z",
    agent_version: "1.0.0",
    agent_metadata: null,
  },
  steps: [],
  evaluators: [],
};

const controlsList: Control[] = [
  {
    id: 1,
    name: "PII Detection",
    control: {
      description: "Detects and masks personally identifiable information",
      enabled: true,
      execution: "server",
      scope: { step_types: ["llm"], stages: ["post"] },
      selector: { path: "output" },
      evaluator: {
        name: "regex",
        config: { pattern: "\\b\\d{3}-\\d{2}-\\d{4}\\b" },
      },
      action: { decision: "deny" },
      tags: ["pii", "compliance"],
    },
  },
  {
    id: 2,
    name: "SQL Injection Guard",
    control: {
      description: "Prevents SQL injection attacks",
      enabled: true,
      execution: "server",
      scope: {
        step_types: ["tool"],
        step_names: ["database_query"],
        step_name_regex: "^db_.*",
        stages: ["pre"],
      },
      selector: { path: "input.query" },
      evaluator: {
        name: "sql",
        config: { mode: "safe" },
      },
      action: { decision: "deny" },
      tags: ["security"],
    },
  },
  {
    id: 3,
    name: "Rate Limiter",
    control: {
      description: "Limits API call frequency",
      enabled: false,
      execution: "server",
      scope: { step_types: ["llm"], stages: ["pre"] },
      selector: { path: "*" },
      evaluator: {
        name: "list",
        config: { values: [], logic: "any", match_on: "match" },
      },
      action: { decision: "allow" },
      tags: [],
    },
  },
];

const controlsResponse: AgentControlsResponse = {
  controls: controlsList,
};

// Control summaries for GET /api/v1/controls (list all controls)
const controlSummariesList: (ControlSummary & { used_by_agent?: { agent_id: string; agent_name: string } | null })[] = [
  {
    id: 1,
    name: "PII Detection",
    description: "Detects and masks personally identifiable information",
    enabled: true,
    execution: "server",
    step_types: ["llm"],
    stages: ["post"],
    tags: ["pii", "compliance"],
    used_by_agent: { agent_id: "agent-1", agent_name: "Customer Support Bot" },
  },
  {
    id: 2,
    name: "SQL Injection Guard",
    description: "Prevents SQL injection attacks",
    enabled: true,
    execution: "server",
    step_types: ["tool"],
    stages: ["pre"],
    tags: ["security"],
    used_by_agent: { agent_id: "agent-2", agent_name: "Data Analysis Agent" },
  },
  {
    id: 3,
    name: "Rate Limiter",
    description: "Limits API call frequency",
    enabled: false,
    execution: "server",
    step_types: ["llm"],
    stages: ["pre"],
    tags: [],
    used_by_agent: null,
  },
];

const listControlsResponse: ListControlsResponse = {
  controls: controlSummariesList,
  pagination: {
    total: controlSummariesList.length,
    limit: 20,
    has_more: false,
    next_cursor: null,
  },
};

const evaluatorsResponse: EvaluatorsResponse = {
  regex: {
    name: "Regex",
    version: "1.0.0",
    description: "Pattern matching using regular expressions",
    requires_api_key: false,
    timeout_ms: 5000,
    config_schema: {
      type: "object",
      properties: {
        pattern: { type: "string", description: "Regular expression pattern" },
      },
      required: ["pattern"],
    },
  },
  list: {
    name: "List",
    version: "1.0.0",
    description: "Match against a list of allowed or blocked values",
    requires_api_key: false,
    timeout_ms: 5000,
    config_schema: {
      type: "object",
      properties: {
        values: { type: "array", items: { type: "string" } },
        logic: { type: "string", enum: ["any", "all"] },
        match_on: { type: "string", enum: ["match", "no_match"] },
      },
      required: ["values"],
    },
  },
  sql: {
    name: "SQL",
    version: "1.0.0",
    description: "SQL injection detection and prevention",
    requires_api_key: false,
    timeout_ms: 5000,
    config_schema: {
      type: "object",
      properties: {
        mode: { type: "string", enum: ["safe", "strict"] },
      },
    },
  },
  json: {
    name: "JSON",
    version: "1.0.0",
    description: "JSON schema validation",
    requires_api_key: false,
    timeout_ms: 5000,
    config_schema: {
      type: "object",
      properties: {
        schema: { type: "object" },
      },
      required: ["schema"],
    },
  },
  "galileo-luna2": {
    name: "Galileo Luna-2",
    version: "1.0.0",
    description: "AI-powered content moderation using Galileo Luna-2",
    requires_api_key: true,
    timeout_ms: 30000,
    config_schema: {
      type: "object",
      properties: {
        threshold: { type: "number" },
      },
    },
  },
};

const statsResponse: StatsResponse = {
  agent_uuid: "agent-1",
  time_range: "1h",
  totals: {
    execution_count: 430,
    match_count: 40,
    non_match_count: 390,
    error_count: 2,
    action_counts: {
      allow: 10,
      deny: 25,
      warn: 3,
      log: 2,
    },
  },
  controls: [
    {
      control_id: 1,
      control_name: "PII Detection",
      execution_count: 150,
      match_count: 25,
      non_match_count: 125,
      allow_count: 5,
      deny_count: 15,
      warn_count: 3,
      log_count: 2,
      error_count: 0,
      avg_confidence: 0.92,
      avg_duration_ms: 45,
    },
    {
      control_id: 2,
      control_name: "SQL Injection Guard",
      execution_count: 80,
      match_count: 10,
      non_match_count: 70,
      allow_count: 0,
      deny_count: 10,
      warn_count: 0,
      log_count: 0,
      error_count: 2,
      avg_confidence: 0.88,
      avg_duration_ms: 32,
    },
    {
      control_id: 3,
      control_name: "Rate Limiter",
      execution_count: 200,
      match_count: 5,
      non_match_count: 195,
      allow_count: 5,
      deny_count: 0,
      warn_count: 0,
      log_count: 0,
      error_count: 0,
      avg_confidence: 0.95,
      avg_duration_ms: 12,
    },
  ],
};

const emptyStatsResponse: StatsResponse = {
  agent_uuid: "agent-1",
  time_range: "1h",
  totals: {
    execution_count: 0,
    match_count: 0,
    non_match_count: 0,
    error_count: 0,
    action_counts: {},
  },
  controls: [],
};

/**
 * Typed mock data for tests
 */
export const mockData = {
  agents: agentsResponse,
  agent: agentResponse,
  controls: controlsResponse,
  listControls: listControlsResponse,
  evaluators: evaluatorsResponse,
  stats: statsResponse,
  emptyStats: emptyStatsResponse,
} as const;

/**
 * Response options for route mocking
 */
type MockResponseOptions<T> =
  | { data: T; status?: number }
  | { error: string; status: number }
  | { handler: () => T | Promise<T> };

/**
 * Helper to fulfill a route with consistent formatting
 */
async function fulfillRoute<T>(
  route: Parameters<Parameters<Page["route"]>[1]>[0],
  options: MockResponseOptions<T>,
  defaultData: T
) {
  if ("error" in options) {
    await route.fulfill({
      status: options.status,
      contentType: "application/json",
      body: JSON.stringify({ error: options.error }),
    });
  } else if ("handler" in options) {
    const data = await options.handler();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(data),
    });
  } else {
    await route.fulfill({
      status: options.status ?? 200,
      contentType: "application/json",
      body: JSON.stringify(options.data ?? defaultData),
    });
  }
}

/**
 * Individual route mock helpers - can be used standalone or with custom data
 */
export const mockRoutes = {
  /** Mock GET /api/v1/agents */
  agents: async (
    page: Page,
    options: MockResponseOptions<ListAgentsResponse> = { data: mockData.agents }
  ) => {
    await page.route("**/api/v1/agents?**", async (route, request) => {
      // Helper to filter agents based on query params (server-side search)
      const getFilteredResponse = (url: string): ListAgentsResponse => {
        const urlObj = new URL(url);
        const nameFilter = urlObj.searchParams.get("name");
        
        let agents = mockData.agents.agents;
        
        // Apply name filter (case-insensitive partial match, like the real API)
        if (nameFilter) {
          const lowerFilter = nameFilter.toLowerCase();
          agents = agents.filter(a => 
            a.agent_name.toLowerCase().includes(lowerFilter)
          );
        }
        
        return {
          agents,
          pagination: {
            total: agents.length,
            limit: 10,
            has_more: false,
            next_cursor: null,
          },
        };
      };

      const url = request.url();
      const filteredData = getFilteredResponse(url);
      
      await fulfillRoute(route, { ...options, data: filteredData }, filteredData);
    });
  },

  /** Mock GET /api/v1/agents/:id and /api/v1/agents/:id/controls */
  agent: async (
    page: Page,
    options: {
      agent?: MockResponseOptions<GetAgentResponse>;
      controls?: MockResponseOptions<AgentControlsResponse>;
    } = {}
  ) => {
    const controlsOpts = options.controls ?? { data: mockData.controls };
    const agentOpts = options.agent ?? { data: mockData.agent };

    // Register controls route first (more specific pattern)
    await page.route("**/api/v1/agents/*/controls", async (route) => {
      await fulfillRoute(route, controlsOpts, mockData.controls);
    });

    // Register agent route second
    await page.route("**/api/v1/agents/*", async (route, request) => {
      const url = request.url();
      // Skip if it's a controls request (handled by separate route above)
      if (url.includes("/controls")) {
        await route.continue();
        return;
      }
      await fulfillRoute(route, agentOpts, mockData.agent);
    });
  },

  /** Mock GET /api/v1/evaluators */
  evaluators: async (
    page: Page,
    options: MockResponseOptions<EvaluatorsResponse> = { data: mockData.evaluators }
  ) => {
    await page.route("**/api/v1/evaluators", async (route) => {
      await fulfillRoute(route, options, mockData.evaluators);
    });
  },

  /** Mock GET /api/v1/controls (list all controls) and PUT /api/v1/controls (create) */
  controlsList: async (
    page: Page,
    options: MockResponseOptions<ListControlsResponse> = { data: mockData.listControls }
  ) => {
    // Helper to filter controls based on query params (server-side search)
    const getFilteredResponse = (url: string): ListControlsResponse => {
      const urlObj = new URL(url);
      const nameFilter = urlObj.searchParams.get("name");
      
      let controls = mockData.listControls.controls;
      
      // Apply name filter (case-insensitive partial match, like the real API)
      if (nameFilter) {
        const lowerFilter = nameFilter.toLowerCase();
        controls = controls.filter(c => 
          c.name.toLowerCase().includes(lowerFilter) ||
          (c.description ?? "").toLowerCase().includes(lowerFilter)
        );
      }
      
      return {
        controls,
        pagination: {
          total: controls.length,
          limit: 20,
          has_more: false,
          next_cursor: null,
        },
      };
    };

    // Handle both with and without query params
    await page.route("**/api/v1/controls?**", async (route, request) => {
      const method = request.method();
      if (method === "GET") {
        const response = getFilteredResponse(request.url());
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(response),
        });
        return;
      }
      await route.continue();
    });
    // Handle base path for GET (list) and PUT (create)
    await page.route("**/api/v1/controls", async (route, request) => {
      const method = request.method();
      if (method === "GET") {
        await fulfillRoute(route, options, mockData.listControls);
        return;
      }
      if (method === "PUT") {
        const body = await request.postDataJSON();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            control_id: 100,
            name: body.name || "New Control",
          }),
        });
        return;
      }
      await route.continue();
    });
  },

  /** @deprecated Use controlsList which now handles both GET and PUT */
  controlCreate: async (_page: Page) => {
    // No-op - handled by controlsList
  },

  /** Mock GET and PUT /api/v1/controls/:id/data */
  controlGetData: async (page: Page) => {
    await page.route("**/api/v1/controls/*/data", async (route, request) => {
      const method = request.method();
      if (method === "GET") {
        // Extract control ID from URL
        const url = request.url();
        const match = url.match(/\/controls\/(\d+)\/data/);
        const controlId = match ? parseInt(match[1], 10) : 1;
        
        // Find matching control from mock data
        const control = controlsList.find(c => c.id === controlId) ?? controlsList[0];
        
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: control.control,
          }),
        });
        return;
      }
      if (method === "PUT") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ success: true }),
        });
        return;
      }
      await route.continue();
    });
  },

  /** @deprecated Use controlGetData which now handles both GET and PUT */
  controlUpdate: async (_page: Page) => {
    // No-op - handled by controlGetData
  },

  /** Mock GET /api/v1/observability/stats */
  stats: async (
    page: Page,
    options: MockResponseOptions<StatsResponse> = { data: mockData.stats }
  ) => {
    await page.route("**/api/v1/observability/stats**", async (route) => {
      await fulfillRoute(route, options, mockData.stats);
    });
  },
};

/**
 * Helper to set up all API route mocking with defaults
 */
export async function mockApiRoutes(page: Page) {
  await mockRoutes.agents(page);
  await mockRoutes.agent(page);
  await mockRoutes.evaluators(page);
  await mockRoutes.controlsList(page);
  await mockRoutes.controlGetData(page);
  await mockRoutes.controlCreate(page);
  await mockRoutes.controlUpdate(page);
  await mockRoutes.stats(page);
}

/**
 * Extended test with mocked API
 */
export const test = base.extend<{ mockedPage: Page }>({
  /* eslint-disable react-hooks/rules-of-hooks */
  mockedPage: async ({ page }, use) => {
    await mockApiRoutes(page);
    await use(page);
  },
  /* eslint-enable react-hooks/rules-of-hooks */
});

export { expect } from "@playwright/test";
