import { MultiSelect, Select, Stack, Switch, TagsInput } from '@mantine/core';

import type {
  ControlActionDecision,
  ControlExecution,
  ControlStage,
  StepSchema,
} from '@/core/api/types';
import {
  labelPropsInline,
  LabelWithTooltip,
} from '@/core/components/label-with-tooltip';

import { StepNameInput } from './step-name-input';
import type { ControlDefinitionFormProps } from './types';

export type ControlDefinitionFormWithStepsProps = ControlDefinitionFormProps & {
  /** Available steps from the agent */
  steps?: StepSchema[];
};

export const ControlDefinitionForm = ({
  form,
  steps,
}: ControlDefinitionFormWithStepsProps) => {
  return (
    <Stack gap="md">
      <Switch
        size="sm"
        color="green.5"
        style={{ width: 'fit-content' }}
        label={
          <LabelWithTooltip
            label="Enabled"
            tooltip="Whether this control is active"
          />
        }
        {...form.getInputProps('enabled', { type: 'checkbox' })}
      />

      <StepNameInput form={form} steps={steps} />

      <MultiSelect
        label={
          <LabelWithTooltip
            label="Stages"
            tooltip="Leave empty to apply to both stages"
          />
        }
        labelProps={labelPropsInline}
        data={[
          { value: 'pre', label: 'Pre (before execution)' },
          { value: 'post', label: 'Post (after execution)' },
        ]}
        size="sm"
        placeholder="All stages"
        clearable
        value={form.values.stages}
        onChange={(value) =>
          form.setFieldValue('stages', value as ControlStage[])
        }
      />

      <Select
        label={
          <LabelWithTooltip
            label="Selector path"
            tooltip="Path to data using dot notation (e.g., 'input', 'output', 'context.user_id', 'name', '*')"
          />
        }
        labelProps={labelPropsInline}
        required
        data={[
          { value: '*', label: '* (entire payload)' },
          { value: 'input', label: 'input' },
          { value: 'output', label: 'output' },
          { value: 'context', label: 'context' },
          { value: 'name', label: 'name' },
          { value: 'type', label: 'type' },
        ]}
        size="sm"
        searchable
        allowDeselect={false}
        {...form.getInputProps('selector_path')}
        onChange={(value) => form.setFieldValue('selector_path', value || '*')}
      />

      <Select
        label={
          <LabelWithTooltip
            label="Action"
            tooltip="What action to take when the control matches"
          />
        }
        labelProps={labelPropsInline}
        data={[
          { value: 'allow', label: 'Allow' },
          { value: 'deny', label: 'Deny' },
          { value: 'warn', label: 'Warn' },
          { value: 'log', label: 'Log' },
        ]}
        size="sm"
        {...form.getInputProps('action_decision')}
        onChange={(value) =>
          form.setFieldValue(
            'action_decision',
            (value as ControlActionDecision) || 'deny'
          )
        }
      />

      <Select
        label={
          <LabelWithTooltip
            label="Execution environment"
            tooltip="Where this control runs: locally in SDK or on the server"
          />
        }
        labelProps={labelPropsInline}
        data={[
          { value: 'server', label: 'Server' },
          { value: 'sdk', label: 'SDK' },
        ]}
        size="sm"
        {...form.getInputProps('execution')}
        onChange={(value) =>
          form.setFieldValue(
            'execution',
            (value as ControlExecution) || 'server'
          )
        }
      />

      <TagsInput
        label={
          <LabelWithTooltip
            label="Step types"
            tooltip="Leave empty to apply to all step types"
          />
        }
        labelProps={labelPropsInline}
        data={['llm', 'tool']}
        size="sm"
        placeholder="All step types"
        clearable
        value={form.values.step_types}
        onChange={(value) => form.setFieldValue('step_types', value)}
      />
    </Stack>
  );
};
