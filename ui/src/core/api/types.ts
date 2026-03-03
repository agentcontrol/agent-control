/**
 * Re-export commonly used types from the generated API types
 * This makes it easier to import types without the verbose path
 */
import type { components, operations } from './generated/api-types';

// =============================================================================
// Error Types (RFC 7807 ProblemDetail)
// =============================================================================

/**
 * Validation error item (GitHub-style field-level error)
 */
export type ValidationErrorItem = {
  /** Resource type where error occurred (e.g., 'Control') */
  resource: string;
  /** Field path that caused the error (e.g., 'data.evaluator.config.pattern') */
  field: string | null;
  /** Machine-readable error code (e.g., 'required', 'invalid_format') */
  code: string;
  /** Human-readable error message */
  message: string;
  /** The invalid value (omitted for sensitive data) */
  value?: unknown;
};

/**
 * RFC 7807 Problem Detail error response
 */
export type ProblemDetail = {
  /** Error type URI */
  type: string;
  /** Short error title */
  title: string;
  /** HTTP status code */
  status: number;
  /** Human-readable error detail */
  detail: string;
  /** Request path */
  instance?: string;
  /** Machine-readable error code */
  error_code: string;
  /** Kubernetes-style reason */
  reason: string;
  /** Array of field-level validation errors */
  errors?: ValidationErrorItem[];
  /** Actionable hint for resolution */
  hint?: string;
};

// Agent types
export type Agent = components['schemas']['Agent'];
export type EvaluatorSchema = components['schemas']['EvaluatorSchema'];
export type StepSchema = components['schemas']['StepSchema'];
export type AgentSummary = components['schemas']['AgentSummary'];
export type ListAgentsResponse = components['schemas']['ListAgentsResponse'];

// Evaluator types
export type EvaluatorInfo = components['schemas']['EvaluatorInfo'];
export type EvaluatorsResponse = Record<string, EvaluatorInfo>;
export type EvaluatorConfigItem = components['schemas']['EvaluatorConfigItem'];
export type ListEvaluatorConfigsResponse =
  components['schemas']['ListEvaluatorConfigsResponse'];

// Request/Response types
export type InitAgentRequest = components['schemas']['InitAgentRequest'];
export type InitAgentResponse = components['schemas']['InitAgentResponse'];
export type GetAgentResponse = components['schemas']['GetAgentResponse'];
export type ControlActionDecision =
  components['schemas']['ControlAction']['decision'];
export type ControlExecution =
  components['schemas']['ControlDefinition-Input']['execution'];
export type ControlStage = NonNullable<
  components['schemas']['ControlScope']['stages']
>[number];
export type ControlScope = components['schemas']['ControlScope'];
export type ControlSelector = components['schemas']['ControlSelector'];
export type ControlAction = components['schemas']['ControlAction'];
export type ControlDefinitionInput =
  components['schemas']['ControlDefinition-Input'];
export type ControlDefinitionOutput =
  components['schemas']['ControlDefinition-Output'];
export type ControlDefinition =
  | ControlDefinitionInput
  | ControlDefinitionOutput;
export type Control = components['schemas']['Control'];
export type AgentControlsResponse =
  components['schemas']['AgentControlsResponse'];

// Control types
export type CreateControlRequest =
  components['schemas']['CreateControlRequest'];
export type CreateControlResponse =
  components['schemas']['CreateControlResponse'];
export type SetControlDataRequest =
  components['schemas']['SetControlDataRequest'];
export type SetControlDataResponse =
  components['schemas']['SetControlDataResponse'];
export type GetControlDataResponse =
  components['schemas']['GetControlDataResponse'];

export type ValidateControlDataRequest =
  components['schemas']['ValidateControlDataRequest'];
export type ValidateControlDataResponse =
  components['schemas']['ValidateControlDataResponse'];
export type ControlSummary = components['schemas']['ControlSummary'];
export type ListControlsResponse =
  components['schemas']['ListControlsResponse'];

export type AgentRef = components['schemas']['AgentRef'];

// Helper type to extract query parameters from operations
type ExtractQueryParams<T> = T extends { parameters: { query?: infer Q } }
  ? Q
  : never;

// Helper type to extract path parameters from operations
type ExtractPathParams<T> = T extends { parameters: { path?: infer P } }
  ? P
  : never;

// Helper type to extract request body from operations
type ExtractRequestBody<T> = T extends {
  requestBody?: { content: { 'application/json': infer B } };
}
  ? B
  : never;

// Specific parameter types using operations
export type ListAgentsQueryParams = ExtractQueryParams<
  operations['list_agents_api_v1_agents_get']
>;
export type GetAgentPathParams = ExtractPathParams<
  operations['get_agent_api_v1_agents__agent_name__get']
>;
export type GetAgentControlsPathParams = ExtractPathParams<
  operations['list_agent_controls_api_v1_agents__agent_name__controls_get']
>;

// Request body types
export type InitAgentRequestBody = ExtractRequestBody<
  operations['init_agent_api_v1_agents_initAgent_post']
>;
