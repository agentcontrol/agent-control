import type { EvaluatorDefinition } from "../types";
import { Luna2Form } from "./form";
import type { Luna2FormValues } from "./types";

/** Helper to safely parse JSON or return null */
const parseJsonOrNull = (value: string): unknown => {
  if (!value || value.trim() === "") return null;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
};

/** Helper to stringify JSON or return empty string */
const stringifyOrEmpty = (value: unknown): string => {
  if (value == null) return "";
  return JSON.stringify(value, null, 2);
};

/** Helper to return string or null */
const stringOrNull = (value: string): string | null =>
  value.trim() === "" ? null : value;

/** Helper to return number or null */
const numberOrNull = (value: number | ""): number | null =>
  value === "" ? null : value;

/**
 * Luna2 (Galileo) evaluator definition.
 *
 * Evaluates content using Galileo's Luna-2 AI metrics for toxicity,
 * prompt injection, PII detection, and more.
 */
export const luna2Evaluator: EvaluatorDefinition<Luna2FormValues> = {
  id: "galileo.luna2",
  displayName: "Galileo Luna-2",

  initialValues: {
    stage_type: "local",
    metric: "",
    operator: "",
    target_value: "",
    stage_name: "",
    stage_version: "",
    galileo_project: "",
    timeout_ms: 10000,
    on_error: "allow",
    payload_field: "",
    metadata: "",
  },

  validate: {
    metric: (value, values) => {
      if (
        (values as Luna2FormValues).stage_type === "local" &&
        (!value || (value as string).trim() === "")
      ) {
        return "Metric is required for local stage";
      }
      return null;
    },
    operator: (value, values) => {
      if (
        (values as Luna2FormValues).stage_type === "local" &&
        (!value || (value as string).trim() === "")
      ) {
        return "Operator is required for local stage";
      }
      return null;
    },
    target_value: (value, values) => {
      if (
        (values as Luna2FormValues).stage_type === "local" &&
        (!value || (value as string).trim() === "")
      ) {
        return "Target value is required for local stage";
      }
      return null;
    },
    stage_name: (value, values) => {
      if (
        (values as Luna2FormValues).stage_type === "central" &&
        (!value || (value as string).trim() === "")
      ) {
        return "Stage name is required for central stage";
      }
      return null;
    },
    metadata: (value) => {
      if (value && (value as string).trim() !== "") {
        try {
          JSON.parse(value as string);
          return null;
        } catch {
          return "Invalid JSON for metadata";
        }
      }
      return null;
    },
  },

  toConfig: (values) => {
    // Parse target value - could be string or number
    let targetValue: string | number | null = values.target_value;
    if (targetValue) {
      const parsed = parseFloat(targetValue);
      targetValue = Number.isNaN(parsed) ? targetValue : parsed;
    } else {
      targetValue = null;
    }

    return {
      stage_type: values.stage_type,
      metric: stringOrNull(values.metric),
      operator: stringOrNull(values.operator),
      target_value: targetValue,
      stage_name: stringOrNull(values.stage_name),
      stage_version: numberOrNull(values.stage_version),
      galileo_project: stringOrNull(values.galileo_project),
      timeout_ms: values.timeout_ms,
      on_error: values.on_error,
      payload_field: stringOrNull(values.payload_field),
      metadata: parseJsonOrNull(values.metadata),
    };
  },

  fromConfig: (config) => ({
    stage_type: (config.stage_type as Luna2FormValues["stage_type"]) || "local",
    metric: (config.metric as Luna2FormValues["metric"]) || "",
    operator: (config.operator as Luna2FormValues["operator"]) || "",
    target_value:
      config.target_value != null ? String(config.target_value) : "",
    stage_name: (config.stage_name as string) || "",
    stage_version: (config.stage_version as number) || "",
    galileo_project: (config.galileo_project as string) || "",
    timeout_ms: (config.timeout_ms as number) || 10000,
    on_error: (config.on_error as Luna2FormValues["on_error"]) || "allow",
    payload_field:
      (config.payload_field as Luna2FormValues["payload_field"]) || "",
    metadata: stringifyOrEmpty(config.metadata),
  }),

  FormComponent: Luna2Form,
};

export type { Luna2FormValues, Luna2Metric, Luna2Operator } from "./types";
