import type { UseFormReturnType } from '@mantine/form';

/**
 * Base interface for evaluator definitions.
 *
 * To add a new evaluator:
 * 1. Create a new folder under `evaluators/` (e.g., `evaluators/my-evaluator/`)
 * 2. Implement `EvaluatorDefinition<YourFormValues>`
 * 3. Export the evaluator from `evaluators/index.ts`
 *
 * The main edit-control component will automatically pick it up.
 */
export type EvaluatorDefinition<TFormValues = any> = {
  /** Unique evaluator ID (must match backend evaluator name) */
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
   * The form component to render for this evaluator.
   * Receives the Mantine form instance as a prop.
   */
  FormComponent: React.ComponentType<{
    form: UseFormReturnType<TFormValues>;
  }>;
};

/**
 * Type helper for creating strongly-typed evaluator definitions.
 * Usage: `const myEvaluator: EvaluatorDefinition<MyFormValues> = { ... }`
 */
export type AnyEvaluatorDefinition = EvaluatorDefinition<any>;

/**
 * Props passed to evaluator form components.
 */
export type EvaluatorFormProps<TFormValues> = {
  form: UseFormReturnType<TFormValues>;
};

/**
 * Utility type for extracting form values type from an evaluator definition.
 */
export type EvaluatorFormValues<T> =
  T extends EvaluatorDefinition<infer V> ? V : never;
