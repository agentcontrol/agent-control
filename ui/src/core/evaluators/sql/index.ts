import type { EvaluatorDefinition } from '../types';
import { SqlForm } from './form';
import type { SqlFormValues } from './types';

/** Helper to split comma-separated string into array */
const splitList = (value: string, uppercase = false): string[] => {
  const items = value
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s !== '');
  return uppercase ? items.map((s) => s.toUpperCase()) : items;
};

/** Helper to return array or null if empty */
const arrayOrNull = (arr: string[]): string[] | null =>
  arr.length > 0 ? arr : null;

/** Helper to return number or null */
const numberOrNull = (value: number | ''): number | null =>
  value === '' ? null : value;

/**
 * SQL evaluator definition.
 *
 * Validates SQL queries for operations, table access, column presence, and complexity.
 */
export const sqlEvaluator: EvaluatorDefinition<SqlFormValues> = {
  id: 'sql',
  displayName: 'SQL',

  initialValues: {
    allow_multi_statements: true,
    max_statements: '',
    blocked_operations: '',
    allowed_operations: '',
    block_ddl: false,
    block_dcl: false,
    allowed_tables: '',
    blocked_tables: '',
    allowed_schemas: '',
    blocked_schemas: '',
    required_columns: '',
    column_presence_logic: 'any',
    column_context: '',
    column_context_scope: 'all',
    require_limit: false,
    max_limit: '',
    max_result_window: '',
    case_sensitive: false,
    dialect: 'postgres',
    max_subquery_depth: '',
    max_joins: '',
    max_union_count: '',
  },

  validate: {
    max_statements: (value, values) => {
      if (value !== '' && !values.allow_multi_statements) {
        return 'Max statements can only be set when multi-statements are allowed';
      }
      return null;
    },
    blocked_operations: (value, values) => {
      if (value && values.allowed_operations) {
        return 'Cannot use both blocked and allowed operations';
      }
      return null;
    },
    allowed_operations: (value, values) => {
      if (value && values.blocked_operations) {
        return 'Cannot use both blocked and allowed operations';
      }
      return null;
    },
    allowed_tables: (value, values) => {
      if (value && values.blocked_tables) {
        return 'Cannot use both allowed and blocked tables';
      }
      return null;
    },
    blocked_tables: (value, values) => {
      if (value && values.allowed_tables) {
        return 'Cannot use both allowed and blocked tables';
      }
      return null;
    },
    allowed_schemas: (value, values) => {
      if (value && values.blocked_schemas) {
        return 'Cannot use both allowed and blocked schemas';
      }
      return null;
    },
    blocked_schemas: (value, values) => {
      if (value && values.allowed_schemas) {
        return 'Cannot use both allowed and blocked schemas';
      }
      return null;
    },
  },

  toConfig: (values) => ({
    // Multi-Statement
    allow_multi_statements: values.allow_multi_statements,
    max_statements: numberOrNull(values.max_statements),
    // Operations - convert comma-separated strings to arrays
    blocked_operations: arrayOrNull(splitList(values.blocked_operations, true)),
    allowed_operations: arrayOrNull(splitList(values.allowed_operations, true)),
    block_ddl: values.block_ddl,
    block_dcl: values.block_dcl,
    // Table/Schema Access
    allowed_tables: arrayOrNull(splitList(values.allowed_tables)),
    blocked_tables: arrayOrNull(splitList(values.blocked_tables)),
    allowed_schemas: arrayOrNull(splitList(values.allowed_schemas)),
    blocked_schemas: arrayOrNull(splitList(values.blocked_schemas)),
    // Column Presence
    required_columns: arrayOrNull(splitList(values.required_columns)),
    column_presence_logic: values.column_presence_logic,
    column_context: values.column_context || null,
    column_context_scope: values.column_context_scope,
    // Limits
    require_limit: values.require_limit,
    max_limit: numberOrNull(values.max_limit),
    max_result_window: numberOrNull(values.max_result_window),
    // Options
    case_sensitive: values.case_sensitive,
    dialect: values.dialect,
    // Query Complexity
    max_subquery_depth: numberOrNull(values.max_subquery_depth),
    max_joins: numberOrNull(values.max_joins),
    max_union_count: numberOrNull(values.max_union_count),
  }),

  fromConfig: (config) => ({
    allow_multi_statements: (config.allow_multi_statements as boolean) ?? true,
    max_statements: (config.max_statements as number) || '',
    // Convert arrays to comma-separated strings
    blocked_operations: ((config.blocked_operations as string[]) || []).join(
      ', '
    ),
    allowed_operations: ((config.allowed_operations as string[]) || []).join(
      ', '
    ),
    block_ddl: (config.block_ddl as boolean) || false,
    block_dcl: (config.block_dcl as boolean) || false,
    allowed_tables: ((config.allowed_tables as string[]) || []).join(', '),
    blocked_tables: ((config.blocked_tables as string[]) || []).join(', '),
    allowed_schemas: ((config.allowed_schemas as string[]) || []).join(', '),
    blocked_schemas: ((config.blocked_schemas as string[]) || []).join(', '),
    required_columns: ((config.required_columns as string[]) || []).join(', '),
    column_presence_logic:
      (config.column_presence_logic as SqlFormValues['column_presence_logic']) ||
      'any',
    column_context:
      (config.column_context as SqlFormValues['column_context']) || '',
    column_context_scope:
      (config.column_context_scope as SqlFormValues['column_context_scope']) ||
      'all',
    require_limit: (config.require_limit as boolean) || false,
    max_limit: (config.max_limit as number) || '',
    max_result_window: (config.max_result_window as number) || '',
    case_sensitive: (config.case_sensitive as boolean) || false,
    dialect: (config.dialect as SqlFormValues['dialect']) || 'postgres',
    max_subquery_depth: (config.max_subquery_depth as number) || '',
    max_joins: (config.max_joins as number) || '',
    max_union_count: (config.max_union_count as number) || '',
  }),

  FormComponent: SqlForm,
};

export type { SqlFormValues } from './types';
