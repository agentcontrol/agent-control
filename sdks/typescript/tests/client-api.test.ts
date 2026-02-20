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
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const request = fetchMock.mock.calls[0]?.[0] as Request;

    expect(request.method).toBe("PUT");
    expect(request.url).toBe("https://api.example.com/api/v1/controls");
    expect(request.headers.get("content-type")).toContain("application/json");
    await expect(request.clone().json()).resolves.toEqual({
      name: "deny-pii",
    });
  });
});
