import type { UseFormReturnType } from "@mantine/form";

import type {
  Control,
  ControlActionDecision,
  ControlExecution,
  ControlStage,
} from "@/core/api/types";

// Re-export evaluator form types for convenience
export type { JsonFormValues } from "@/core/evaluators/json/types";
export type { ListFormValues } from "@/core/evaluators/list/types";
export type {
  Luna2FormValues,
  Luna2Metric,
  Luna2Operator,
} from "@/core/evaluators/luna2/types";
export type { RegexFormValues } from "@/core/evaluators/regex/types";
export type { SqlFormValues } from "@/core/evaluators/sql/types";

export type ConfigViewMode = "form" | "json";
export type JsonViewMode = "tree" | "raw";

// Form values type for control definition
// Uses snake_case to match API field names directly
export interface ControlDefinitionFormValues {
  name: string;
  enabled: boolean;
  step_types: string[];
  stages: ControlStage[];
  step_names: string;
  step_name_regex: string;
  step_name_mode: "names" | "regex";
  selector_path: string;
  action_decision: ControlActionDecision;
  execution: ControlExecution;
}

/** Mode for the EditControl modal */
export type EditControlMode = "create" | "edit";

export interface EditControlProps {
  /** Whether the modal is open */
  opened: boolean;
  /** The control to edit/create template */
  control: Control | null;
  /** Agent ID for invalidating queries on save */
  agentId: string;
  /** Mode: 'create' for new control, 'edit' for existing */
  mode?: EditControlMode;
  /** Callback when modal is closed */
  onClose: () => void;
  /** Callback when save succeeds */
  onSuccess?: () => void;
}

export interface EvaluatorJsonViewProps {
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  jsonViewMode: JsonViewMode;
  onJsonViewModeChange: (mode: JsonViewMode) => void;
  rawJsonText: string;
  onRawJsonTextChange: (text: string) => void;
  rawJsonError: string | null;
  /** Optional height for the editor area */
  height?: number;
}

export interface ControlDefinitionFormProps {
  form: UseFormReturnType<ControlDefinitionFormValues>;
}
