/**
 * Re-export commonly used types from the generated API types
 * This makes it easier to import types without the verbose path
 */
import type { components, operations } from "./generated/api-types";

// Agent types
export type AgentSummary = components["schemas"]["AgentSummary"];
export type ListAgentsResponse = components["schemas"]["ListAgentsResponse"];
export type Agent = components["schemas"]["Agent"];
export type AgentTool = components["schemas"]["AgentTool"];
export type EvaluatorSchema = components["schemas"]["EvaluatorSchema"];

// Plugin types
export type PluginInfo = components["schemas"]["PluginInfo"];
export type PluginsResponse = Record<string, PluginInfo>;

// Request/Response types
export type InitAgentRequest = components["schemas"]["InitAgentRequest"];
export type InitAgentResponse = components["schemas"]["InitAgentResponse"];
export type GetAgentResponse = components["schemas"]["GetAgentResponse"];
export type AgentControlsResponse =
  components["schemas"]["AgentControlsResponse"];
export type Control = components["schemas"]["Control"];
export type ControlDefinition = components["schemas"]["ControlDefinition"];

// Extracted enums from ControlDefinition
export type ControlAppliesTo = ControlDefinition["applies_to"];
export type ControlCheckStage = ControlDefinition["check_stage"];
export type ControlActionDecision =
  components["schemas"]["ControlAction"]["decision"];

// Control types
export type CreateControlRequest = components["schemas"]["CreateControlRequest"];
export type CreateControlResponse =
  components["schemas"]["CreateControlResponse"];
export type SetControlDataRequest =
  components["schemas"]["SetControlDataRequest"];
export type SetControlDataResponse =
  components["schemas"]["SetControlDataResponse"];
export type GetControlDataResponse =
  components["schemas"]["GetControlDataResponse"];

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
  requestBody?: { content: { "application/json": infer B } };
}
  ? B
  : never;

// Specific parameter types using operations
export type ListAgentsQueryParams = ExtractQueryParams<
  operations["list_agents_api_v1_agents_get"]
>;
export type GetAgentPathParams = ExtractPathParams<
  operations["get_agent_api_v1_agents__agent_id__get"]
>;
export type GetAgentControlsPathParams = ExtractPathParams<
  operations["list_agent_controls_api_v1_agents__agent_id__controls_get"]
>;

// Request body types
export type InitAgentRequestBody = ExtractRequestBody<
  operations["init_agent_api_v1_agents_initAgent_post"]
>;
