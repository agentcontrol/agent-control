import { AgentControlClient } from "./client";

export { AgentControlClient } from "./client";
export { control } from "./control";
export { ControlViolationError } from "./errors";
export type { ControlAction, EvaluationResult } from "./errors";
export type {
  AgentControlInitOptions,
  AgentsApi,
  ControlsApi,
  EvaluationApi,
  EvaluatorConfigsApi,
  EvaluatorsApi,
  ObservabilityApi,
  PoliciesApi,
  StepSchema,
  SystemApi,
} from "./client";
export type { JsonObject, JsonPrimitive, JsonValue } from "./types";
export * from "./types";

const agentControl = new AgentControlClient();

export default agentControl;
