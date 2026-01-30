/**
 * Luna2 metric types supported by Galileo.
 */
export type Luna2Metric =
  | "input_toxicity"
  | "output_toxicity"
  | "input_sexism"
  | "output_sexism"
  | "prompt_injection"
  | "pii_detection"
  | "hallucination"
  | "tone"
  | "";

/**
 * Luna2 comparison operator types.
 */
export type Luna2Operator =
  | "gt"
  | "lt"
  | "gte"
  | "lte"
  | "eq"
  | "contains"
  | "any"
  | "";

/**
 * Form values for the Luna2 (Galileo) evaluator.
 * Uses snake_case to match API field names directly.
 */
export interface Luna2FormValues {
  stage_type: "local" | "central";
  // Local stage fields
  metric: Luna2Metric;
  operator: Luna2Operator;
  target_value: string; // Can be string or number, stored as string in form
  // Central stage fields
  stage_name: string;
  stage_version: number | "";
  // Common fields
  galileo_project: string;
  timeout_ms: number;
  on_error: "allow" | "deny";
  payload_field: "input" | "output" | "";
  metadata: string; // JSON string
}
