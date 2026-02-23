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
import {
  IconAlertCircle,
  IconCircleCheck,
  IconCircleX,
  IconInfoCircle,
} from '@tabler/icons-react';
import { useMemo, useState } from 'react';

import type { StepSchema } from '@/core/api/types';

import type { ControlDefinitionFormProps } from './types';

export type StepNameInputProps = ControlDefinitionFormProps & {
  /** Available steps from the agent */
  steps?: StepSchema[];
};

export function StepNameInput({ form, steps = [] }: StepNameInputProps) {
  const isRegexMode = form.values.step_name_mode === 'regex';
  const [searchValue, setSearchValue] = useState('');

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

  // Step options for dropdown - ensure steps is always an array
  const stepOptions = useMemo(() => {
    if (!steps || !Array.isArray(steps)) return [];
    return steps.map((step) => ({
      value: step.name,
      label: step.name,
    }));
  }, [steps]);

  const handleStepNamesChange = (values: string[]) => {
    // Empty means "all steps" on the server
    if (values.length === 0) {
      form.setFieldValue('step_names', '');
      return;
    }

    form.setFieldValue('step_names', values.join(', '));
  };

  const selectedSummary = useMemo(() => {
    if (selectedStepNames.length === 0) {
      // When no steps exist, avoid showing "All steps" alongside "No steps available"
      return steps.length > 0 ? 'All steps' : '';
    }
    if (selectedStepNames.length === 1) return selectedStepNames[0];
    return `${selectedStepNames[0]} +${selectedStepNames.length - 1}`;
  }, [selectedStepNames, steps.length]);

  const regexMatchInfo = useMemo(() => {
    const pattern = form.values.step_name_regex.trim();
    if (!pattern) {
      return {
        hasPattern: false,
        isValid: true,
        matchCount: 0,
        matchedStepNames: [] as string[],
        errorMessage: '',
      };
    }

    try {
      const regex = new RegExp(pattern);
      const matchedStepNames = steps
        .map((step) => step.name)
        .filter((stepName) => regex.test(stepName));

      return {
        hasPattern: true,
        isValid: true,
        matchCount: matchedStepNames.length,
        matchedStepNames,
        errorMessage: '',
      };
    } catch (error) {
      return {
        hasPattern: true,
        isValid: false,
        matchCount: 0,
        matchedStepNames: [] as string[],
        errorMessage: error instanceof Error ? error.message : 'Invalid regex',
      };
    }
  }, [form.values.step_name_regex, steps]);

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
          rightSection={
            regexMatchInfo.hasPattern ? (
              <Tooltip
                multiline
                label={
                  regexMatchInfo.isValid ? (
                    <Stack gap={4}>
                      <Text size="xs">
                        {regexMatchInfo.matchCount} matching step
                        {regexMatchInfo.matchCount === 1 ? '' : 's'}
                      </Text>
                      {regexMatchInfo.matchCount > 0 ? (
                        <Text size="xs">
                          {regexMatchInfo.matchedStepNames.join(', ')}
                        </Text>
                      ) : (
                        <Text size="xs">No step names matched.</Text>
                      )}
                    </Stack>
                  ) : (
                    <Text size="xs">
                      Invalid regex: {regexMatchInfo.errorMessage}
                    </Text>
                  )
                }
              >
                <Group gap={4} wrap="nowrap">
                  {regexMatchInfo.isValid ? (
                    regexMatchInfo.matchCount > 0 ? (
                      <IconCircleCheck
                        size={14}
                        color="var(--mantine-color-green-6)"
                      />
                    ) : (
                      <IconCircleX
                        size={14}
                        color="var(--mantine-color-gray-6)"
                      />
                    )
                  ) : (
                    <IconAlertCircle
                      size={14}
                      color="var(--mantine-color-red-6)"
                    />
                  )}
                  <Text size="xs" c={regexMatchInfo.isValid ? 'dimmed' : 'red'}>
                    {regexMatchInfo.isValid ? regexMatchInfo.matchCount : '!'}
                  </Text>
                </Group>
              </Tooltip>
            ) : undefined
          }
          rightSectionPointerEvents="all"
          {...form.getInputProps('step_name_regex')}
        />
      ) : (
        <Box pos="relative">
          <MultiSelect
            data-testid="step-name-select"
            size="sm"
            placeholder={steps.length > 0 ? '' : 'No steps available'}
            data={stepOptions}
            value={selectedStepNames}
            onChange={handleStepNamesChange}
            clearable
            searchable
            searchValue={searchValue}
            onSearchChange={setSearchValue}
            checkIconPosition="right"
            styles={{
              // Keep pillsList visible because it contains the focusable input field.
              // Hiding pillsList breaks keyboard interaction for MultiSelect.
              pill: { display: 'none' },
            }}
          />
          {searchValue.trim() === '' ? (
            <Text
              size="sm"
              c={selectedStepNames.length === 0 ? 'dimmed' : undefined}
              style={{
                position: 'absolute',
                left: 12,
                top: '50%',
                transform: 'translateY(-50%)',
                pointerEvents: 'none',
                maxWidth: 'calc(100% - 72px)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {selectedSummary}
            </Text>
          ) : null}
        </Box>
      )}
    </Box>
  );
}
