/**
 * Utilities for mapping API errors to form fields.
 *
 * Since form fields use snake_case to match API field names directly,
 * the mapping logic is simple - just extract the field name from the path.
 */

import type { UseFormReturnType } from '@mantine/form';

import type { ValidationErrorItem } from '@/core/api/types';

/**
 * Mapping result indicating which form and field an API error belongs to
 */
type FieldMapping = {
  form: 'definition' | 'evaluator';
  field: string;
};

/**
 * Map an API error field path to a form field.
 *
 * API field paths look like:
 * - "name" (control name)
 * - "data.scope.step_types" (definition field)
 * - "data.condition.selector.path" → selector_path (definition field)
 * - "data.condition.evaluator.config.pattern" (evaluator config field)
 *
 * Since forms use snake_case, we can directly use the API field names.
 *
 * @param apiField The field path from the API error
 * @returns The form and field name, or null if unmapped
 */
export function mapApiFieldToFormField(
  apiField: string | null
): FieldMapping | null {
  if (!apiField) return null;

  // Handle "name" directly (control name)
  if (apiField === 'name') {
    return { form: 'definition', field: 'name' };
  }

  // Handle "data." prefix
  const dataPrefix = 'data.';
  if (!apiField.startsWith(dataPrefix)) {
    return null;
  }

  const fieldPath = apiField.slice(dataPrefix.length);

  const leafConditionPrefix = 'condition.';
  if (fieldPath.startsWith(leafConditionPrefix)) {
    const conditionField = fieldPath.slice(leafConditionPrefix.length);

    if (conditionField === 'selector.path') {
      return { form: 'definition', field: 'selector_path' };
    }

    const evalPrefix = 'evaluator.';
    if (conditionField.startsWith(evalPrefix)) {
      let configField = conditionField.slice(evalPrefix.length);
      if (configField.startsWith('config.')) {
        configField = configField.slice('config.'.length);
      }

      const firstDotIndex = configField.indexOf('.');
      const field =
        firstDotIndex > 0 ? configField.slice(0, firstDotIndex) : configField;

      return { form: 'evaluator', field };
    }

    return null;
  }

  // Handle definition fields
  if (fieldPath === 'action.decision') {
    return { form: 'definition', field: 'action_decision' };
  }
  if (fieldPath === 'action.steering_context') {
    return { form: 'definition', field: 'action_steering_context' };
  }
  if (fieldPath.startsWith('scope.')) {
    const scopeField = fieldPath.slice('scope.'.length);
    const scopeFieldBase = scopeField.split('.')[0];
    const scopeMap: Record<string, string> = {
      step_types: 'step_types',
      step_names: 'step_names',
      step_name_regex: 'step_name_regex',
      stages: 'stages',
    };
    const mappedField = scopeMap[scopeFieldBase];
    if (mappedField) {
      return { form: 'definition', field: mappedField };
    }
  }

  // For other definition fields, use the field path directly
  // (e.g., "execution", "enabled")
  const firstDotIndex = fieldPath.indexOf('.');
  const field =
    firstDotIndex > 0 ? fieldPath.slice(0, firstDotIndex) : fieldPath;

  return { form: 'definition', field };
}

/**
 * Apply API validation errors to Mantine forms.
 *
 * @param errors Array of validation errors from API
 * @param definitionForm The control definition form
 * @param evaluatorForm The evaluator config form
 * @returns Array of errors that couldn't be mapped to form fields
 */
export function applyApiErrorsToForms(
  errors: ValidationErrorItem[] | undefined,
  definitionForm: UseFormReturnType<any>,
  evaluatorForm?: UseFormReturnType<any> | null
): ValidationErrorItem[] {
  if (!errors || errors.length === 0) {
    return [];
  }

  const unmappedErrors: ValidationErrorItem[] = [];

  for (const error of errors) {
    const mapping = mapApiFieldToFormField(error.field);

    if (mapping) {
      if (mapping.form === 'definition') {
        definitionForm.setFieldError(mapping.field, error.message);
      } else if (mapping.form === 'evaluator' && evaluatorForm) {
        evaluatorForm.setFieldError(mapping.field, error.message);
      } else if (mapping.form === 'evaluator') {
        unmappedErrors.push(error);
      }
    } else {
      unmappedErrors.push(error);
    }
  }

  return unmappedErrors;
}

/**
 * Sanitize a string for use in a control name segment.
 * Control names must match ^[a-zA-Z0-9][a-zA-Z0-9_-]*$
 */
export function sanitizeControlNamePart(s: string): string {
  const sanitized = s
    .trim()
    .replace(/\s+/g, '-')
    .replace(/[^a-zA-Z0-9_-]/g, '')
    .replace(/^[-_]+/, '');
  return sanitized || 'control';
}
