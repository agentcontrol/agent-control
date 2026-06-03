import type { EvaluatorDefinition } from '../types';
import { LunaForm } from './form';
import type { LunaFormValues } from './types';

/** Numeric operators that require a numeric threshold. */
const NUMERIC_OPERATORS = new Set<LunaFormValues['operator']>([
  'gt',
  'gte',
  'lt',
  'lte',
]);

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

/** Helper to return trimmed string or null */
const stringOrNull = (value: string): string | null =>
  value.trim() === '' ? null : value;

/**
 * Coerce a threshold form value (always a string) into the API representation.
 * Numeric-looking values become numbers; empty becomes null; anything else
 * is passed through as a string (e.g. for `eq`/`contains` on text scores).
 */
const coerceThreshold = (value: string): string | number | null => {
  const trimmed = value.trim();
  if (trimmed === '') return null;
  const num = Number(trimmed);
  return Number.isNaN(num) ? trimmed : num;
};

/**
 * Luna (Galileo) direct scorer evaluator definition.
 *
 * Invokes a Galileo Luna scorer and applies a local threshold comparison to
 * the returned score. One of scorer label, scorer ID, or scorer version ID
 * must be provided.
 */
export const lunaEvaluator: EvaluatorDefinition<LunaFormValues> = {
  id: 'galileo.luna',
  displayName: 'Galileo Luna',

  initialValues: {
    scorer_label: '',
    scorer_id: '',
    scorer_version_id: '',
    threshold: '0.5',
    operator: 'gte',
    payload_field: 'input',
    timeout_ms: 10000,
    scorer_config: '',
  },

  validate: {
    scorer_label: (_value, values) => {
      const v = values as LunaFormValues;
      if (
        v.scorer_label.trim() === '' &&
        v.scorer_id.trim() === '' &&
        v.scorer_version_id.trim() === ''
      ) {
        return 'Provide a scorer label, scorer ID, or scorer version ID';
      }
      return null;
    },
    threshold: (value, values) => {
      const v = values as LunaFormValues;
      const raw = ((value as string) ?? '').trim();
      if (v.operator === 'any') return null;
      if (raw === '') return 'Threshold is required unless operator is "Any"';
      if (NUMERIC_OPERATORS.has(v.operator) && Number.isNaN(Number(raw))) {
        return 'A numeric threshold is required for numeric operators';
      }
      return null;
    },
    scorer_config: (value) => {
      if (value && (value as string).trim() !== '') {
        try {
          JSON.parse(value as string);
          return null;
        } catch {
          return 'Invalid JSON for scorer config';
        }
      }
      return null;
    },
    timeout_ms: (value) => {
      if (value === '' || value == null) return 'Timeout is required';
      if (typeof value !== 'number' || Number.isNaN(value)) {
        return 'Timeout must be a number';
      }
      if (value < 1000 || value > 60000) {
        return 'Timeout must be between 1000 and 60000 ms';
      }
      return null;
    },
  },

  toConfig: (values) => ({
    scorer_label: stringOrNull(values.scorer_label),
    scorer_id: stringOrNull(values.scorer_id),
    scorer_version_id: stringOrNull(values.scorer_version_id),
    threshold: coerceThreshold(values.threshold),
    operator: values.operator,
    payload_field: values.payload_field,
    timeout_ms: values.timeout_ms,
    // `scorer_config` is sent to the API under the `config` key.
    config: parseJsonOrNull(values.scorer_config),
  }),

  fromConfig: (config) => ({
    scorer_label: (config.scorer_label as string) || '',
    scorer_id: (config.scorer_id as string) || '',
    scorer_version_id: (config.scorer_version_id as string) || '',
    threshold: config.threshold != null ? String(config.threshold) : '',
    operator: (config.operator as LunaFormValues['operator']) || 'gte',
    payload_field:
      (config.payload_field as LunaFormValues['payload_field']) || 'input',
    timeout_ms: (config.timeout_ms as number) || 10000,
    scorer_config: stringifyOrEmpty(config.config),
  }),

  FormComponent: LunaForm,
};

export type { LunaFormValues, LunaOperator, LunaPayloadField } from './types';
