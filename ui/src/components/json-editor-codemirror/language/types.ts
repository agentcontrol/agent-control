import type { StepSchema } from '@/core/api/types';
import type {
  JsonEditorEvaluatorOption,
  JsonEditorMode,
  JsonSchema,
} from '@/core/page-components/agent-detail/modals/edit-control/types';

export type JsonPath = Array<string | number>;

export type JsonEditorCodeMirrorContext = {
  mode: JsonEditorMode;
  schema?: JsonSchema | null;
  evaluators?: JsonEditorEvaluatorOption[];
  activeEvaluatorId?: string | null;
  steps?: StepSchema[];
};

export type JsonEditorTextEdit = {
  offset: number;
  length: number;
  newText: string;
};

export type SchemaCursor = {
  schema: JsonSchema | null;
  rootSchema: JsonSchema | null;
};

export const ROOT_SELECTOR_PATHS = [
  '*',
  'input',
  'output',
  'context',
  'name',
  'type',
];

export const SCHEMA_COMPOSITION_KEYS = ['$ref', 'allOf', 'anyOf', 'oneOf'];

export const MAX_HINT_VALUES = 6;
