import { AgentControlClient } from "./client";
import { _registerDefaultClient } from "./control";

export { AgentControlClient } from "./client";
export { control, guard, check } from "./control";
export { ControlViolationError, ControlSteerError } from "./errors";
export type { ControlAction, EvaluationResult } from "./errors";
export type { ControlOptions, GuardContext, CheckStep } from "./control";
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
_registerDefaultClient(agentControl);

export default agentControl;
