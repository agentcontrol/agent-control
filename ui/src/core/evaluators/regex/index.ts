import type { EvaluatorDefinition } from '../types';
import { RegexForm } from './form';
import type { RegexFormValues } from './types';

/**
 * Regex evaluator definition.
 *
 * Validates content against a regular expression pattern.
 */
export const regexEvaluator: EvaluatorDefinition<RegexFormValues> = {
  id: 'regex',
  displayName: 'Regex',

  initialValues: {
    pattern: '^.*$',
  },

  validate: {
    pattern: (value) => {
      if (!value || (value as string).trim() === '') {
        return 'Pattern is required';
      }
      try {
        new RegExp(value as string);
        return null;
      } catch (error) {
        return `Invalid regex pattern: ${
          error instanceof Error ? error.message : 'Unknown error'
        }`;
      }
    },
  },

  toConfig: (values) => ({
    pattern: values.pattern,
  }),

  fromConfig: (config) => ({
    pattern: (config.pattern as string) || '^.*$',
  }),

  FormComponent: RegexForm,
};

export type { RegexFormValues } from './types';
