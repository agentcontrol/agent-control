import { describe, expect, it, vi } from "vitest";

import { AgentControlClient } from "../src/client";
import { control, _registerDefaultClient } from "../src/control";
import { ControlViolationError, ControlSteerError } from "../src/errors";

async function mockClient(evaluateResult: Record<string, unknown>) {
  const client = new AgentControlClient();
  await client.init({
    agentName: "test-agent",
    serverUrl: "http://localhost:8000",
    apiKey: "test-key",
    registerAgent: false,
  });

  const evaluateMock = vi.fn().mockResolvedValue(evaluateResult);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  vi.spyOn(client, "evaluation", "get").mockReturnValue({ evaluate: evaluateMock } as any);

  _registerDefaultClient(client);
  return { client, evaluateMock };
}

const SAFE_RESULT: Record<string, unknown> = { isSafe: true, confidence: 1.0 };

describe("control", () => {
  it("throws when client is not initialized", async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    _registerDefaultClient(null as any);
    const wrapped = control(async (v: string) => v);
    await expect(wrapped("hi")).rejects.toThrow("not initialized");
  });

  it("passes through when evaluation is safe", async () => {
    await mockClient(SAFE_RESULT);

    const wrapped = control(async (value: string) => `echo:${value}`, {
      stepName: "test-fn",
    });

    await expect(wrapped("hello")).resolves.toBe("echo:hello");
  });

  it("calls evaluate for pre and post stages", async () => {
    const { evaluateMock } = await mockClient(SAFE_RESULT);

    const wrapped = control(async (msg: string) => `reply:${msg}`, {
      stepName: "chat",
    });
    await wrapped("hi");

    expect(evaluateMock).toHaveBeenCalledTimes(2);

    const preCall = evaluateMock.mock.calls[0][0];
    expect(preCall.body.stage).toBe("pre");
    expect(preCall.body.step.name).toBe("chat");
    expect(preCall.body.step.input).toBe("hi");

    const postCall = evaluateMock.mock.calls[1][0];
    expect(postCall.body.stage).toBe("post");
    expect(postCall.body.step.output).toBe("reply:hi");
  });

  it("throws ControlViolationError on deny", async () => {
    await mockClient({
      isSafe: false,
      confidence: 0.9,
      matches: [
        {
          controlId: 1,
          controlName: "block-pii",
          action: "deny",
          result: { matched: true, confidence: 0.9, message: "PII detected" },
        },
      ],
    });

    const wrapped = control(async (msg: string) => msg, { stepName: "chat" });

    await expect(wrapped("ssn: 123-45-6789")).rejects.toThrow(ControlViolationError);
  });

  it("throws ControlSteerError on steer", async () => {
    await mockClient({
      isSafe: false,
      confidence: 0.8,
      matches: [
        {
          controlId: 2,
          controlName: "tone-check",
          action: "steer",
          result: { matched: true, confidence: 0.8, message: "Tone too aggressive" },
          steeringContext: { message: "Please use a friendlier tone" },
        },
      ],
    });

    const wrapped = control(async (msg: string) => msg, { stepName: "chat" });

    await expect(wrapped("rude message")).rejects.toThrow(ControlSteerError);
  });

  it("does not execute function when pre-check denies", async () => {
    await mockClient({
      isSafe: false,
      confidence: 1.0,
      matches: [
        {
          controlId: 1,
          controlName: "blocker",
          action: "deny",
          result: { matched: true, confidence: 1.0, message: "Blocked" },
        },
      ],
    });

    const fn = vi.fn().mockResolvedValue("should not run");
    const wrapped = control(fn, { stepName: "blocked-fn" });

    await expect(wrapped()).rejects.toThrow(ControlViolationError);
    expect(fn).not.toHaveBeenCalled();
  });

  it("supports name-first overload", async () => {
    const { evaluateMock } = await mockClient(SAFE_RESULT);

    const wrapped = control("my-step", async (x: number) => x * 2);
    await wrapped(5);

    expect(evaluateMock.mock.calls[0][0].body.step.name).toBe("my-step");
  });
});
