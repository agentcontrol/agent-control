import type { EvaluatorDefinition } from '../types';
import { ListForm } from './form';
import type { ListFormValues } from './types';

/**
 * List evaluator definition.
 *
 * Validates content against a list of values with configurable matching logic.
 */
export const listEvaluator: EvaluatorDefinition<ListFormValues> = {
  id: 'list',
  displayName: 'List',

  initialValues: {
    values: '',
    logic: 'any',
    match_on: 'match',
    match_mode: 'exact',
    case_sensitive: false,
  },

  validate: {
    values: (value) => {
      const trimmedValues = (value as string)
        .split('\n')
        .filter((v) => v.trim() !== '');
      if (trimmedValues.length === 0) {
        return 'At least one value is required';
      }
      return null;
    },
  },

  toConfig: (values) => {
    // Convert newline-separated string to array, pass rest through directly
    const rawValues = typeof values.values === 'string' ? values.values : '';
    const valuesList = rawValues.split('\n').filter((v) => v.trim() !== '');
    return {
      ...values,
      values: valuesList,
    };
  },

  fromConfig: (config) => ({
    // Convert array to newline-separated string, pass rest through directly
    values: ((config.values as string[]) || []).join('\n'),
    logic: (config.logic as ListFormValues['logic']) || 'any',
    match_on: (config.match_on as ListFormValues['match_on']) || 'match',
    match_mode: (config.match_mode as ListFormValues['match_mode']) || 'exact',
    case_sensitive: (config.case_sensitive as boolean) || false,
  }),

  FormComponent: ListForm,
};

export type { ListFormValues } from './types';
