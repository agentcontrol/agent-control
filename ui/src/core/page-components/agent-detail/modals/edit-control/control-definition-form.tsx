import {
  Autocomplete,
  MultiSelect,
  Select,
  Stack,
  Switch,
  TagsInput,
} from '@mantine/core';

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

      <Autocomplete
        label={
          <LabelWithTooltip
            label="Selector path"
            tooltip="Path to data. Use * for full step or a root (input, output, name, type, context); subpaths allowed (e.g. input.args.command)."
          />
        }
        labelProps={labelPropsInline}
        required
        data={['*', 'input', 'output', 'name', 'type', 'context']}
        renderOption={({ option, ...others }) => (
          <div {...others}>
            {option.value === '*' ? '* (entire payload)' : option.value}
          </div>
        )}
        size="sm"
        placeholder="e.g., input or input.args.command"
        {...form.getInputProps('selector_path')}
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
