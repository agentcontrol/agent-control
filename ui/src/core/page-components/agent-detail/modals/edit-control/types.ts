import type { UseFormReturnType } from '@mantine/form';
import type { ReactNode } from 'react';

import type {
  Control,
  ControlActionDecision,
  ControlExecution,
  ControlStage,
  EvaluatorSchema,
  ProblemDetail,
  StepSchema,
} from '@/core/api/types';

// Re-export evaluator form types for convenience
export type { JsonFormValues } from '@/core/evaluators/json/types';
export type { ListFormValues } from '@/core/evaluators/list/types';
export type {
  Luna2FormValues,
  Luna2Metric,
  Luna2Operator,
} from '@/core/evaluators/luna2/types';
export type { RegexFormValues } from '@/core/evaluators/regex/types';
export type { SqlFormValues } from '@/core/evaluators/sql/types';

export type ConfigViewMode = 'form' | 'json';
export type ControlEditorMode = 'form' | 'json';
export type JsonEditorMode = 'control' | 'evaluator-config' | 'template';

export type JsonSchema = Record<string, unknown>;

export type JsonEditorEvaluatorOption = {
  id: string;
  label: string;
  description?: string | null;
  source: 'global' | 'agent';
  configSchema?: EvaluatorSchema['config_schema'] | null;
};

// Form values type for control definition
// Uses snake_case to match API field names directly
export type ControlDefinitionFormValues = {
  name: string;
  description?: string;
  enabled: boolean;
  step_types: string[];
  stages: ControlStage[];
  step_names: string;
  step_name_regex: string;
  step_name_mode: 'names' | 'regex';
  selector_path: string;
  action_decision: ControlActionDecision;
  action_steering_context?: string;
  execution: ControlExecution;
};

/** Mode for the EditControl modal */
export type EditControlMode = 'create' | 'edit';

export type EditControlProps = {
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
};

export type JsonEditorViewProps = {
  /** Current JSON text shown in the editor */
  jsonText: string;
  /** Update handler when JSON text changes */
  handleJsonChange: (text: string) => void;
  /** Syntactic/validation error message for the JSON text */
  jsonError?: string | null;
  setJsonError?: (error: string | null) => void;
  validationError?: ProblemDetail | null;
  setValidationError?: (error: ProblemDetail | null) => void;
  onValidateConfig?: (
    config: Record<string, unknown>,
    options?: { signal?: AbortSignal }
  ) => Promise<void>;
  onValidationStatusChange?: (
    status: 'idle' | 'validating' | 'valid' | 'invalid'
  ) => void;
  validateDebounceMs?: number;
  /** Optional height for the editor area */
  height?: number;
  /** Optional label for the JSON editor */
  label?: string;
  /** Optional tooltip for the JSON editor label */
  tooltip?: string;
  /** Optional helper text shown below the editor */
  helperText?: ReactNode;
  /** Optional test id for the editor root */
  testId?: string;
  /** Optional Monaco mode for context-aware completion */
  editorMode?: JsonEditorMode;
  /** Optional JSON schema used for Monaco diagnostics */
  schema?: JsonSchema | null;
  /** Available evaluators for name/config autocomplete */
  evaluators?: JsonEditorEvaluatorOption[];
  /** Active evaluator id for evaluator-config mode */
  activeEvaluatorId?: string | null;
  /** Agent step schemas used for selector path suggestions */
  steps?: StepSchema[];
  /** Parameter names from the template (for template mode $param completions) */
  templateParameterNames?: string[];
};

export type ControlDefinitionFormProps = {
  form: UseFormReturnType<ControlDefinitionFormValues>;
  disableSelectorPath?: boolean;
};
