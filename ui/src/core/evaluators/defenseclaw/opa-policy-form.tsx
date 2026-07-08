import { Divider, Select, Stack } from '@mantine/core';

import type { EvaluatorFormProps } from '../types';
import {
  DEFENSECLAW_SEVERITIES,
  type DefenseClawOpaPolicyFormValues,
} from './types';

const severityOptions = DEFENSECLAW_SEVERITIES.map((severity) => ({
  value: severity,
  label: severity,
}));

export const DefenseClawOpaPolicyForm = ({
  form,
}: EvaluatorFormProps<DefenseClawOpaPolicyFormValues>) => (
  <Stack gap="md">
    <Divider label="Policy" labelPosition="left" />
    <Select
      label="Domain"
      data={[{ value: 'guardrail', label: 'Guardrail' }]}
      allowDeselect={false}
      required
      {...form.getInputProps('domain')}
    />
    <Select
      label="Block at"
      data={severityOptions}
      allowDeselect={false}
      required
      {...form.getInputProps('block_at')}
    />
    <Select
      label="Alert at"
      data={severityOptions}
      allowDeselect={false}
      required
      {...form.getInputProps('alert_at')}
    />
    <Select
      label="Cisco trust level"
      data={[{ value: 'full', label: 'Full' }]}
      allowDeselect={false}
      required
      {...form.getInputProps('cisco_trust_level')}
    />
  </Stack>
);
