import type { EvaluatorDefinition } from '../types';
import { JsonForm } from './form';
import type { JsonFormValues } from './types';

/** Helper to safely parse JSON or return null */
const parseJsonOrNull = (value: string): unknown => {
  if (!value || value.trim() === '') return null;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
};

/** Helper to stringify JSON or return empty string */
const stringifyOrEmpty = (value: unknown): string => {
  if (value == null) return '';
  return JSON.stringify(value, null, 2);
};

/**
 * JSON evaluator definition.
 *
 * Validates JSON structure, types, constraints, and patterns.
 */
export const jsonEvaluator: EvaluatorDefinition<JsonFormValues> = {
  id: 'json',
  displayName: 'JSON',

  initialValues: {
    json_schema: '',
    required_fields: '',
    field_types: '',
    field_constraints: '',
    field_patterns: '',
    allow_extra_fields: true,
    allow_null_required: false,
    pattern_match_logic: 'all',
    case_sensitive_enums: true,
    allow_invalid_json: false,
  },

  validate: {
    json_schema: (value) => {
      if (value && (value as string).trim() !== '') {
        try {
          JSON.parse(value as string);
          return null;
        } catch {
          return 'Invalid JSON schema';
        }
      }
      return null;
    },
    field_types: (value) => {
      if (value && (value as string).trim() !== '') {
        try {
          JSON.parse(value as string);
          return null;
        } catch {
          return 'Invalid JSON for field types';
        }
      }
      return null;
    },
    field_constraints: (value) => {
      if (value && (value as string).trim() !== '') {
        try {
          JSON.parse(value as string);
          return null;
        } catch {
          return 'Invalid JSON for field constraints';
        }
      }
      return null;
    },
    field_patterns: (value) => {
      if (value && (value as string).trim() !== '') {
        try {
          JSON.parse(value as string);
          return null;
        } catch {
          return 'Invalid JSON for field patterns';
        }
      }
      return null;
    },
  },

  toConfig: (values) => {
    // Convert comma-separated string to array, parse JSON fields
    const requiredFields = values.required_fields
      .split(',')
      .map((f) => f.trim())
      .filter((f) => f !== '');
    return {
      json_schema: parseJsonOrNull(values.json_schema),
      required_fields: requiredFields.length > 0 ? requiredFields : null,
      field_types: parseJsonOrNull(values.field_types),
      field_constraints: parseJsonOrNull(values.field_constraints),
      field_patterns: parseJsonOrNull(values.field_patterns),
      allow_extra_fields: values.allow_extra_fields,
      allow_null_required: values.allow_null_required,
      pattern_match_logic: values.pattern_match_logic,
      case_sensitive_enums: values.case_sensitive_enums,
      allow_invalid_json: values.allow_invalid_json,
    };
  },

  fromConfig: (config) => ({
    json_schema: stringifyOrEmpty(config.json_schema),
    required_fields: ((config.required_fields as string[]) || []).join(', '),
    field_types: stringifyOrEmpty(config.field_types),
    field_constraints: stringifyOrEmpty(config.field_constraints),
    field_patterns: stringifyOrEmpty(config.field_patterns),
    allow_extra_fields: (config.allow_extra_fields as boolean) ?? true,
    allow_null_required: (config.allow_null_required as boolean) || false,
    pattern_match_logic:
      (config.pattern_match_logic as JsonFormValues['pattern_match_logic']) ||
      'all',
    case_sensitive_enums: (config.case_sensitive_enums as boolean) ?? true,
    allow_invalid_json: (config.allow_invalid_json as boolean) || false,
  }),

  FormComponent: JsonForm,
};

export type { JsonFormValues } from './types';
