import type { ControlDefinition } from '@/core/api/types';
import type { AnyRuleDefinition } from '@/core/rules';
import { getRule } from '@/core/rules';

export type LeafConditionDetails = {
  selectorPath: string;
  ruleName: string;
  ruleConfig: Record<string, unknown>;
};

export type ControlConditionState = {
  leafCondition: LeafConditionDetails | null;
  ruleId: string;
  rule: AnyRuleDefinition | undefined;
  canEditLeafCondition: boolean;
};

function getLeafConditionDetails(
  definition: ControlDefinition
): LeafConditionDetails | null {
  const condition = definition.condition;
  if (!condition.selector || !condition.rule) {
    return null;
  }

  return {
    selectorPath: condition.selector.path ?? '*',
    ruleName: condition.rule.name,
    ruleConfig: condition.rule.config,
  };
}

export function getControlConditionState(
  definition: ControlDefinition
): ControlConditionState {
  const leafCondition = getLeafConditionDetails(definition);
  const ruleId = leafCondition?.ruleName ?? '';
  const rule = getRule(ruleId);

  return {
    leafCondition,
    ruleId,
    rule,
    canEditLeafCondition: Boolean(leafCondition),
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
    rule: {
      name: leafCondition.ruleName,
      config: finalConfig,
    },
  };
}
