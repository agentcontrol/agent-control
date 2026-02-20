import {
  Box,
  Group,
  MultiSelect,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { IconInfoCircle } from '@tabler/icons-react';
import { useMemo } from 'react';

import type { StepSchema } from '@/core/api/types';

import type { ControlDefinitionFormProps } from './types';

export type StepNameInputProps = ControlDefinitionFormProps & {
  /** Available steps from the agent */
  steps?: StepSchema[];
};

export function StepNameInput({ form, steps = [] }: StepNameInputProps) {
  const isRegexMode = form.values.step_name_mode === 'regex';

  const handleRegexToggle = (enabled: boolean) => {
    form.setFieldValue('step_name_mode', enabled ? 'regex' : 'names');
  };

  // Convert comma-separated string to array for MultiSelect
  const selectedStepNames = useMemo(() => {
    if (isRegexMode || !form.values.step_names) return [];
    return form.values.step_names
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
  }, [form.values.step_names, isRegexMode]);

  // Step options for dropdown
  const stepOptions = useMemo(() => {
    return steps.map((step) => ({
      value: step.name,
      label: step.name,
    }));
  }, [steps]);

  const handleStepNamesChange = (values: string[]) => {
    // Convert array back to comma-separated string
    form.setFieldValue('step_names', values.join(', '));
  };

  return (
    <Box>
      <Group gap="xs" mb={4} wrap="nowrap">
        <Group gap={4}>
          <Text size="sm" fw={500}>
            Step name
          </Text>
          <Tooltip
            label={
              <Stack gap={0}>
                <Text size="xs">
                  {isRegexMode
                    ? 'Optional RE2 pattern to match step names.'
                    : 'Select step names to scope this control.'}
                </Text>
                <Text size="xs">
                  {isRegexMode
                    ? 'Toggle off to select step names from dropdown.'
                    : 'Toggle on to use a regex pattern instead.'}
                </Text>
              </Stack>
            }
          >
            <IconInfoCircle size={14} color="gray" />
          </Tooltip>
        </Group>
        <Switch
          size="xs"
          label="Regex"
          checked={isRegexMode}
          onChange={(e) => handleRegexToggle(e.currentTarget.checked)}
        />
      </Group>
      {isRegexMode ? (
        <TextInput
          size="sm"
          placeholder="^db_.*"
          {...form.getInputProps('step_name_regex')}
        />
      ) : (
        <MultiSelect
          size="sm"
          placeholder={
            steps.length > 0
              ? 'Select step names (leave empty for all steps)'
              : 'No steps available'
          }
          data={stepOptions}
          value={selectedStepNames}
          onChange={handleStepNamesChange}
          clearable
          searchable
        />
      )}
    </Box>
  );
}
