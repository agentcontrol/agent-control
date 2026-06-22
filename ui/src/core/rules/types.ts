import type { UseFormReturnType } from '@mantine/form';

/**
 * Base interface for rule definitions.
 *
 * To add a new rule:
 * 1. Create a new folder under `rules/` (e.g., `rules/my-rule/`)
 * 2. Implement `RuleDefinition<YourFormValues>`
 * 3. Export the rule from `rules/index.ts`
 *
 * The main edit-control component will automatically pick it up.
 */
export type RuleDefinition<TFormValues = any> = {
  /** Unique rule ID (must match backend rule name) */
  id: string;

  /** Human-readable display name */
  displayName: string;

  /** Initial form values when creating a new control */
  initialValues: TFormValues;

  /**
   * Validation rules for the form.
   * Uses Mantine form validation format.
   * @see https://mantine.dev/form/validation/
   */
  validate?: Record<
    string,
    (value: unknown, values: TFormValues) => string | null
  >;

  /**
   * Convert form values to API config format.
   * Called when saving the control.
   */
  toConfig: (values: TFormValues) => Record<string, unknown>;

  /**
   * Convert API config to form values.
   * Called when loading an existing control.
   */
  fromConfig: (config: Record<string, unknown>) => TFormValues;

  /**
   * The form component to render for this rule.
   * Receives the Mantine form instance as a prop.
   */
  FormComponent: React.ComponentType<{
    form: UseFormReturnType<TFormValues>;
  }>;
};

/**
 * Type helper for creating strongly-typed rule definitions.
 * Usage: `const myRule: RuleDefinition<MyFormValues> = { ... }`
 */
export type AnyRuleDefinition = RuleDefinition<any>;

/**
 * Props passed to rule form components.
 */
export type RuleFormProps<TFormValues> = {
  form: UseFormReturnType<TFormValues>;
};

/**
 * Utility type for extracting form values type from a rule definition.
 */
export type RuleFormValues<T> = T extends RuleDefinition<infer V> ? V : never;
