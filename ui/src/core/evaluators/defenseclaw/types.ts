export const DEFENSECLAW_SEVERITIES = [
  'LOW',
  'MEDIUM',
  'HIGH',
  'CRITICAL',
] as const;

export type DefenseClawSeverity = (typeof DEFENSECLAW_SEVERITIES)[number];

export type DefenseClawRuleFormValue = {
  id: string;
  pattern: string;
  title: string;
  severity: DefenseClawSeverity;
  confidence: number;
  tags: string[];
};

export type DefenseClawRulePackFormValues = {
  rules: DefenseClawRuleFormValue[];
};

export type DefenseClawOpaPolicyFormValues = {
  domain: 'guardrail';
  block_at: DefenseClawSeverity;
  alert_at: DefenseClawSeverity;
  cisco_trust_level: 'full';
};
