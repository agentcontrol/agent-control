import { describe, expect, it } from "vitest";

import { evaluationRequestToJSON } from "../src/generated/models/evaluation-request";
import type { EvaluationRequest } from "../src/generated/models/evaluation-request";

describe("EvaluationRequest serialization", () => {
  const baseRequest: EvaluationRequest = {
    agentName: "test-agent-01",
    stage: "pre",
    step: {
      type: "llm",
      name: "chat",
      input: "hello",
    },
  };

  it("omits target fields from the wire payload when unset", () => {
    const wire = JSON.parse(evaluationRequestToJSON(baseRequest)) as Record<string, unknown>;
    expect(wire.agent_name).toBe("test-agent-01");
    expect("target_type" in wire).toBe(false);
    expect("target_id" in wire).toBe(false);
  });

  it("forwards targetType and targetId as snake_case on the wire", () => {
    const request: EvaluationRequest = {
      ...baseRequest,
      targetType: "environment",
      targetId: "env-prod-123",
    };

    const wire = JSON.parse(evaluationRequestToJSON(request)) as Record<string, unknown>;
    expect(wire.target_type).toBe("environment");
    expect(wire.target_id).toBe("env-prod-123");
    expect("targetType" in wire).toBe(false);
    expect("targetId" in wire).toBe(false);
  });

  it("accepts null for target fields without failing", () => {
    const request: EvaluationRequest = {
      ...baseRequest,
      targetType: null,
      targetId: null,
    };

    const wire = JSON.parse(evaluationRequestToJSON(request)) as Record<string, unknown>;
    expect(wire.target_type).toBeNull();
    expect(wire.target_id).toBeNull();
  });
});
