/**
 * Luna comparison operator types.
 *
 * Numeric operators (gt, gte, lt, lte) require a numeric threshold.
 */
export type LunaOperator =
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'eq'
  | 'ne'
  | 'contains'
  | 'any';

/**
 * Which scorer input side to evaluate for scalar selected data.
 */
export type LunaPayloadField = 'input' | 'output';

/**
 * Form values for the Luna (Galileo) direct scorer evaluator.
 * Uses snake_case to match API field names directly.
 *
 * One of `scorer_label`, `scorer_id`, or `scorer_version_id` is required.
 */
export type LunaFormValues = {
  // Scorer identity (at least one required)
  scorer_label: string;
  scorer_id: string;
  scorer_version_id: string;
  // Local comparison
  threshold: string; // Can be a number or string; stored as string in the form
  operator: LunaOperator;
  // Advanced
  payload_field: LunaPayloadField;
  timeout_ms: number | '';
  scorer_config: string; // JSON string, serialized to the `config` API field
};
