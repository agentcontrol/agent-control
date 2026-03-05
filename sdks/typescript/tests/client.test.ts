import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentControlClient } from "../src/client";
import { control } from "../src/control";
import { _clearStepRegistry } from "../src/_control_registry";

describe("AgentControlClient", () => {
  afterEach(() => {
    _clearStepRegistry();
    vi.unstubAllGlobals();
  });

  it("stores init config", async () => {
    const client = new AgentControlClient();

    await client.init({
      agentName: "test-agent",
      serverUrl: "http://localhost:8000",
      apiKey: "test-key",
      registerAgent: false,
    });

    expect(client.initialized).toBe(true);
    expect(client.config?.agentName).toBe("test-agent");
  });

  it("registers auto-discovered control steps during init", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ created: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    // Register two steps via control() wrappers.
    control("chat", async () => "ok");
    control("lookup_customer", async () => ({ found: true }), { type: "tool" });

    const client = new AgentControlClient();
    await client.init({
      agentName: "test-agent",
      serverUrl: "http://localhost:8000",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    const body = await request.clone().json();
    expect(body.steps).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ name: "chat", type: "llm" }),
        expect.objectContaining({ name: "lookup_customer", type: "tool" }),
      ]),
    );
  });

});
