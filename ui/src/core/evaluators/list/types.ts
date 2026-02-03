/**
 * Form values for the list evaluator.
 * Uses snake_case to match API field names directly.
 */
export interface ListFormValues {
  /** Newline-separated list of values */
  values: string;
  /** Match logic: any or all */
  logic: "any" | "all";
  /** When to trigger: on match or no match */
  match_on: "match" | "no_match";
  /** Match mode: exact or contains */
  match_mode: "exact" | "contains";
  /** Whether matching is case sensitive */
  case_sensitive: boolean;
}
