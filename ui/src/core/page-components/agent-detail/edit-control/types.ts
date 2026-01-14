import type { UseFormReturnType } from "@mantine/form";

import type {
  Control,
  ControlActionDecision,
  ControlAppliesTo,
  ControlCheckStage,
} from "@/core/api/types";

export type ConfigViewMode = "form" | "json";
export type JsonViewMode = "tree" | "raw";

// Form values type for control definition
export interface ControlDefinitionFormValues {
  name: string;
  enabled: boolean;
  appliesTo: ControlAppliesTo;
  checkStage: ControlCheckStage;
  selectorPath: string;
  actionDecision: ControlActionDecision;
  local: boolean;
}

// Form values for regex evaluator
export interface RegexFormValues {
  pattern: string;
}

// Form values for list evaluator
export interface ListFormValues {
  values: string; // Stored as newline-separated string in form, converted to array on submit
  logic: "any" | "all";
  matchOn: "match" | "no_match";
  matchMode: "exact" | "contains";
  caseSensitive: boolean;
}

export interface EditControlProps {
  opened: boolean;
  control: Control | null;
  onClose: () => void;
  onSave: (data: Control) => void;
}

export interface RegexFormProps {
  form: UseFormReturnType<RegexFormValues>;
}

export interface ListFormProps {
  form: UseFormReturnType<ListFormValues>;
}

export interface EvaluatorConfigFormProps {
  pluginId: string;
  regexForm: UseFormReturnType<RegexFormValues>;
  listForm: UseFormReturnType<ListFormValues>;
}

export interface EvaluatorJsonViewProps {
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  jsonViewMode: JsonViewMode;
  onJsonViewModeChange: (mode: JsonViewMode) => void;
  rawJsonText: string;
  onRawJsonTextChange: (text: string) => void;
  rawJsonError: string | null;
}

export interface ControlDefinitionFormProps {
  form: UseFormReturnType<ControlDefinitionFormValues>;
}
