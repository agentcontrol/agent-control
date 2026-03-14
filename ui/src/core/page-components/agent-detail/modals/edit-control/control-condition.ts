import type { ControlDefinition } from '@/core/api/types';
import type { AnyEvaluatorDefinition } from '@/core/evaluators';
import { getEvaluator } from '@/core/evaluators';

const COMPOSITE_CONDITION_EDITING_MESSAGE =
  'This control uses a composite condition tree. This PR keeps the old single-condition UI, so saving will preserve the existing tree without editing it.';

export type LeafConditionDetails = {
  selectorPath: string;
  evaluatorName: string;
  evaluatorConfig: Record<string, unknown>;
};

export type ControlConditionState = {
  leafCondition: LeafConditionDetails | null;
  evaluatorId: string;
  evaluator: AnyEvaluatorDefinition | undefined;
  canEditLeafCondition: boolean;
  conditionEditingMessage: string | null;
};

function getLeafConditionDetails(
  definition: ControlDefinition
): LeafConditionDetails | null {
  const condition = definition.condition;
  if (!condition.selector || !condition.evaluator) {
    return null;
  }

  return {
    selectorPath: condition.selector.path ?? '*',
    evaluatorName: condition.evaluator.name,
    evaluatorConfig: condition.evaluator.config,
  };
}

export function getControlConditionState(
  definition: ControlDefinition
): ControlConditionState {
  const leafCondition = getLeafConditionDetails(definition);
  const evaluatorId = leafCondition?.evaluatorName ?? '';
  const evaluator = getEvaluator(evaluatorId);

  return {
    leafCondition,
    evaluatorId,
    evaluator,
    canEditLeafCondition: Boolean(leafCondition),
    conditionEditingMessage: leafCondition
      ? null
      : COMPOSITE_CONDITION_EDITING_MESSAGE,
  };
}

export function buildEditableCondition(
  definition: ControlDefinition,
  leafCondition: LeafConditionDetails | null,
  selectorPath: string,
  finalConfig: Record<string, unknown>
): ControlDefinition['condition'] {
  if (!leafCondition) {
    return definition.condition;
  }

  return {
    selector: {
      path: selectorPath,
    },
    evaluator: {
      name: leafCondition.evaluatorName,
      config: finalConfig,
    },
  };
}
