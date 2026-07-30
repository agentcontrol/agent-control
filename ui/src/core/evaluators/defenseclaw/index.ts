import type { EvaluatorDefinition } from '../types';
import { DefenseClawOpaPolicyForm } from './opa-policy-form';
import {
  createBlankDefenseClawRule,
  DefenseClawRulePackForm,
} from './rule-pack-form';
import {
  DEFENSECLAW_SEVERITIES,
  type DefenseClawOpaPolicyFormValues,
  type DefenseClawRuleFormValue,
  type DefenseClawRulePackFormValues,
} from './types';

const severityValues = new Set<string>(DEFENSECLAW_SEVERITIES);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const normalizeRule = (value: unknown): DefenseClawRuleFormValue => {
  if (!isRecord(value)) return createBlankDefenseClawRule();
  return {
    id: typeof value.id === 'string' ? value.id : '',
    pattern: typeof value.pattern === 'string' ? value.pattern : '',
    title: typeof value.title === 'string' ? value.title : '',
    severity: severityValues.has(String(value.severity))
      ? (value.severity as DefenseClawRuleFormValue['severity'])
      : 'HIGH',
    confidence: typeof value.confidence === 'number' ? value.confidence : 0.99,
    tags: Array.isArray(value.tags)
      ? value.tags.filter((tag): tag is string => typeof tag === 'string')
      : [],
  };
};

const validateRules = (value: unknown): string | null => {
  if (!Array.isArray(value) || value.length === 0) {
    return 'At least one rule is required';
  }
  const rules = value as DefenseClawRuleFormValue[];
  const ids = rules.map((rule) => rule.id.trim());
  if (
    rules.some(
      (rule) => !rule.id.trim() || !rule.title.trim() || !rule.pattern.trim()
    )
  ) {
    return 'Every rule requires an ID, title, and pattern';
  }
  if (new Set(ids).size !== ids.length) return 'Rule IDs must be unique';
  if (
    rules.some(
      (rule) =>
        !Number.isFinite(rule.confidence) ||
        rule.confidence < 0 ||
        rule.confidence > 1
    )
  ) {
    return 'Rule confidence must be between 0 and 1';
  }
  if (rules.some((rule) => !severityValues.has(rule.severity))) {
    return 'Every rule requires a supported severity';
  }
  if (rules.some((rule) => rule.tags.some((tag) => !tag.trim()))) {
    return 'Rule tags cannot be blank';
  }
  return null;
};

export const defenseClawRulePackEvaluator: EvaluatorDefinition<DefenseClawRulePackFormValues> =
  {
    id: 'defenseclaw.rule_pack',
    displayName: 'DefenseClaw Rule Pack',
    defaultExecution: 'sdk',
    supportedExecutions: ['sdk'],
    initialValues: { rules: [createBlankDefenseClawRule()] },
    validate: { rules: validateRules },
    toConfig: (values) => ({
      schema_version: 1,
      rule_pack: {
        version: 1,
        category: 'agent-control',
        rules: values.rules,
      },
    }),
    fromConfig: (config) => {
      const rulePack = isRecord(config.rule_pack) ? config.rule_pack : {};
      const rules = Array.isArray(rulePack.rules)
        ? rulePack.rules.map(normalizeRule)
        : [];
      return {
        rules: rules.length > 0 ? rules : [createBlankDefenseClawRule()],
      };
    },
    FormComponent: DefenseClawRulePackForm,
  };

export const defenseClawOpaPolicyEvaluator: EvaluatorDefinition<DefenseClawOpaPolicyFormValues> =
  {
    id: 'defenseclaw.opa_policy',
    displayName: 'DefenseClaw OPA Policy',
    defaultExecution: 'sdk',
    supportedExecutions: ['sdk'],
    initialValues: {
      domain: 'guardrail',
      block_at: 'HIGH',
      alert_at: 'MEDIUM',
      cisco_trust_level: 'full',
    },
    validate: {
      domain: (value) =>
        value === 'guardrail' ? null : 'Domain must be guardrail',
      block_at: (value) =>
        severityValues.has(String(value))
          ? null
          : 'Select a supported block severity',
      alert_at: (value) =>
        severityValues.has(String(value))
          ? null
          : 'Select a supported alert severity',
      cisco_trust_level: (value) =>
        value === 'full' ? null : 'Cisco trust level must be full',
    },
    toConfig: (values) => ({ schema_version: 1, policy: { ...values } }),
    fromConfig: (config) => {
      const policy = isRecord(config.policy) ? config.policy : {};
      return {
        domain: 'guardrail',
        block_at: severityValues.has(String(policy.block_at))
          ? (policy.block_at as DefenseClawOpaPolicyFormValues['block_at'])
          : 'HIGH',
        alert_at: severityValues.has(String(policy.alert_at))
          ? (policy.alert_at as DefenseClawOpaPolicyFormValues['alert_at'])
          : 'MEDIUM',
        cisco_trust_level: 'full',
      };
    },
    FormComponent: DefenseClawOpaPolicyForm,
  };

export type {
  DefenseClawOpaPolicyFormValues,
  DefenseClawRuleFormValue,
  DefenseClawRulePackFormValues,
  DefenseClawSeverity,
} from './types';
