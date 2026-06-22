/**
 * Rule Registry
 *
 * This module exports all available rules and provides
 * utilities for working with them.
 *
 * ## Adding a New Rule
 *
 * 1. Create a new folder under `rules/` (e.g., `rules/my-rule/`)
 * 2. Create the following files:
 *    - `types.ts` - Form value types
 *    - `form.tsx` - React form component
 *    - `index.ts` - Rule definition (implements RuleDefinition interface)
 * 3. Import and add the rule to the `rules` array below
 * 4. That's it! The main edit-control component will automatically pick it up.
 *
 * @example
 * ```typescript
 * // rules/my-rule/index.ts
 * import type { RuleDefinition } from "../types";
 * import { MyForm } from "./form";
 * import type { MyFormValues } from "./types";
 *
 * export const myRule: RuleDefinition<MyFormValues> = {
 *   id: "my-rule",
 *   displayName: "My Rule",
 *   initialValues: { ... },
 *   validate: { ... },
 *   toConfig: (values) => ({ ... }),
 *   fromConfig: (config) => ({ ... }),
 *   FormComponent: MyForm,
 * };
 * ```
 */

import { jsonRule } from './json';
import { listRule } from './list';
import { lunaRule } from './luna';
import { regexRule } from './regex';
import { sqlRule } from './sql';
import type { AnyRuleDefinition } from './types';

/**
 * All registered rules.
 * Add new rules here to make them available in the UI.
 */
export const rules: AnyRuleDefinition[] = [
  regexRule,
  listRule,
  jsonRule,
  sqlRule,
  lunaRule,
];

/**
 * Map of rule ID to rule for quick lookup.
 */
export const ruleRegistry = new Map<string, AnyRuleDefinition>(
  rules.map((rule) => [rule.id, rule])
);

/**
 * Get a rule by ID.
 * Returns undefined if the rule is not found.
 */
export const getRule = (id: string): AnyRuleDefinition | undefined =>
  ruleRegistry.get(id);

/**
 * Check if a rule exists.
 */
export const hasRule = (id: string): boolean => ruleRegistry.has(id);

// Re-export types and individual rules for direct imports
export { jsonRule } from './json';
export { listRule } from './list';
export { lunaRule } from './luna';
export { regexRule } from './regex';
export { sqlRule } from './sql';
export type { AnyRuleDefinition, RuleDefinition, RuleFormProps } from './types';
