/**
 * Evaluator Registry
 *
 * This module exports all available evaluators and provides
 * utilities for working with them.
 *
 * ## Adding a New Evaluator
 *
 * 1. Create a new folder under `evaluators/` (e.g., `evaluators/my-evaluator/`)
 * 2. Create the following files:
 *    - `types.ts` - Form value types
 *    - `form.tsx` - React form component
 *    - `index.ts` - Evaluator definition (implements EvaluatorDefinition interface)
 * 3. Import and add the evaluator to the `evaluators` array below
 * 4. That's it! The main edit-control component will automatically pick it up.
 *
 * @example
 * ```typescript
 * // evaluators/my-evaluator/index.ts
 * import type { EvaluatorDefinition } from "../types";
 * import { MyForm } from "./form";
 * import type { MyFormValues } from "./types";
 *
 * export const myEvaluator: EvaluatorDefinition<MyFormValues> = {
 *   id: "my-evaluator",
 *   displayName: "My Evaluator",
 *   initialValues: { ... },
 *   validate: { ... },
 *   toConfig: (values) => ({ ... }),
 *   fromConfig: (config) => ({ ... }),
 *   FormComponent: MyForm,
 * };
 * ```
 */

import { jsonEvaluator } from './json';
import { listEvaluator } from './list';
import { luna2Evaluator } from './luna2';
import { regexEvaluator } from './regex';
import { sqlEvaluator } from './sql';
import type { AnyEvaluatorDefinition } from './types';

/**
 * All registered evaluators.
 * Add new evaluators here to make them available in the UI.
 */
export const evaluators: AnyEvaluatorDefinition[] = [
  regexEvaluator,
  listEvaluator,
  jsonEvaluator,
  sqlEvaluator,
  luna2Evaluator,
];

/**
 * Map of evaluator ID to evaluator for quick lookup.
 */
export const evaluatorRegistry = new Map<string, AnyEvaluatorDefinition>(
  evaluators.map((evaluator) => [evaluator.id, evaluator])
);

/**
 * Get an evaluator by ID.
 * Returns undefined if the evaluator is not found.
 */
export const getEvaluator = (id: string): AnyEvaluatorDefinition | undefined =>
  evaluatorRegistry.get(id);

/**
 * Check if an evaluator exists.
 */
export const hasEvaluator = (id: string): boolean => evaluatorRegistry.has(id);

// Re-export types and individual evaluators for direct imports
export { jsonEvaluator } from './json';
export { listEvaluator } from './list';
export { luna2Evaluator } from './luna2';
export { regexEvaluator } from './regex';
export { sqlEvaluator } from './sql';
export type {
  AnyEvaluatorDefinition,
  EvaluatorDefinition,
  EvaluatorFormProps,
} from './types';
