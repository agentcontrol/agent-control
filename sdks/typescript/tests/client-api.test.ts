import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentControlClient } from "../src/client";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json",
    },
  });
}

describe("AgentControlClient API wiring", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it.each([12.5, 0, null, undefined])(
    "preserves per-control execution durations through evaluation responses (%s)",
    async (executionDurationMs) => {
      const match = {
        control_id: 1,
        control_name: "Example control",
        action: "observe",
        result: { matched: true, confidence: 1.0 },
        execution_duration_ms: executionDurationMs,
      };
      vi.mocked(globalThis.fetch).mockResolvedValueOnce(
        jsonResponse({
          is_safe: true,
          confidence: 1.0,
          matches: [match],
          non_matches: [
            { ...match, result: { matched: false, confidence: 1.0 } },
          ],
          errors: [
            {
              ...match,
              result: { matched: false, confidence: 0.0, error: "Evaluation failed" },
            },
          ],
        }),
      );
      const client = new AgentControlClient();
      client.init({ agentName: "test-agent", serverUrl: "https://api.example.com" });

      const response = await client.evaluation.evaluate({
        agentName: "test-agent",
        stage: "pre",
        step: { type: "llm", name: "answer", input: "hello" },
      });

      expect(response.matches?.[0]?.executionDurationMs).toBe(executionDurationMs);
      expect(response.nonMatches?.[0]?.executionDurationMs).toBe(executionDurationMs);
      expect(response.errors?.[0]?.executionDurationMs).toBe(executionDurationMs);
    },
  );

  it("throws when endpoint groups are accessed before init", () => {
    const client = new AgentControlClient();

    expect(() => client.agents).toThrow(/not initialized/i);
  });

  it("builds GET requests with query params and X-API-Key auth", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        agents: [],
        pagination: {
          has_more: false,
          limit: 5,
          next_cursor: null,
          total: 0,
        },
      }),
    );

    const client = new AgentControlClient();
    client.init({
      agentName: "test-agent",
      serverUrl: "https://api.example.com",
      apiKey: "test-api-key",
    });

    await client.agents.list({
      limit: 5,
      name: "support",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const request = fetchMock.mock.calls[0]?.[0] as Request;

    expect(request.method).toBe("GET");
    expect(request.url).toBe("https://api.example.com/api/v1/agents?limit=5&name=support");
    expect(request.headers.get("X-API-Key")).toBe("test-api-key");
  });

  it("passes debugLogger through to the generated SDK", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        agents: [],
        pagination: {
          has_more: false,
          limit: 20,
          next_cursor: null,
          total: 0,
        },
      }),
    );

    const debugLogger = {
      group: vi.fn(),
      groupEnd: vi.fn(),
      log: vi.fn(),
    };

    const client = new AgentControlClient();
    client.init({
      agentName: "test-agent",
      serverUrl: "https://api.example.com",
      debugLogger,
    });

    await client.agents.list();

    expect(debugLogger.group).toHaveBeenCalledWith(
      "> Request: GET https://api.example.com/api/v1/agents",
    );
    expect(debugLogger.group).toHaveBeenCalledWith(
      "< Response: GET https://api.example.com/api/v1/agents",
    );
    expect(debugLogger.log).toHaveBeenCalledWith("Status Code:", 200, "");
  });

  it("builds JSON request bodies for write operations", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        control_id: 101,
      }),
    );

    const client = new AgentControlClient();
    client.init({
      agentName: "test-agent",
      serverUrl: "https://api.example.com",
    });

    await client.controls.create({
      name: "deny-pii",
      data: {
        action: {
          decision: "deny",
        },
        condition: {
          evaluator: {
            name: "regex",
            config: { pattern: "pii" },
          },
          selector: {
            path: "input",
          },
        },
        execution: "server",
        scope: {
          stages: ["pre"],
          stepTypes: ["llm"],
        },
      },
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const request = fetchMock.mock.calls[0]?.[0] as Request;

    expect(request.method).toBe("PUT");
    expect(request.url).toBe("https://api.example.com/api/v1/controls");
    expect(request.headers.get("content-type")).toContain("application/json");
    await expect(request.clone().json()).resolves.toEqual({
      name: "deny-pii",
      data: {
        action: {
          decision: "deny",
        },
        condition: {
          evaluator: {
            name: "regex",
            config: { pattern: "pii" },
          },
          selector: {
            path: "input",
          },
        },
        enabled: true,
        execution: "server",
        scope: {
          stages: ["pre"],
          step_types: ["llm"],
        },
      },
    });
  });

  it("defaults initAgent conflict_mode to overwrite", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        created: true,
      }),
    );

    const client = new AgentControlClient();
    client.init({
      agentName: "test-agent",
      serverUrl: "https://api.example.com",
    });

    await client.agents.init({
      agent: {
        agentId: "550e8400-e29b-41d4-a716-446655440000",
        agentName: "test-agent",
      },
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    await expect(request.clone().json()).resolves.toMatchObject({
      conflict_mode: "overwrite",
    });
  });
});
