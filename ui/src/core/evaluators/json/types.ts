/**
 * Form values for the JSON evaluator.
 * Uses snake_case to match API field names directly.
 */
export interface JsonFormValues {
  /** JSON Schema specification (Draft 7 or later) */
  json_schema: string;
  /** Comma-separated list of required fields (dot notation) */
  required_fields: string;
  /** JSON mapping of field paths to expected types */
  field_types: string;
  /** JSON mapping of field paths to constraints */
  field_constraints: string;
  /** JSON mapping of field paths to regex patterns */
  field_patterns: string;
  /** Allow fields not defined in field_types */
  allow_extra_fields: boolean;
  /** Allow null values in required fields */
  allow_null_required: boolean;
  /** Logic for field_patterns validation */
  pattern_match_logic: "all" | "any";
  /** Case-sensitive enum matching */
  case_sensitive_enums: boolean;
  /** Treat invalid JSON as non-match instead of triggering */
  allow_invalid_json: boolean;
}
