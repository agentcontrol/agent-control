import {
  ActionIcon,
  Box,
  Divider,
  Group,
  NumberInput,
  Paper,
  Select,
  Stack,
  TagsInput,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import { Button } from '@rungalileo/jupiter-ds';
import { IconTrash } from '@tabler/icons-react';

import type { EvaluatorFormProps } from '../types';
import {
  DEFENSECLAW_SEVERITIES,
  type DefenseClawRuleFormValue,
  type DefenseClawRulePackFormValues,
} from './types';

export const createBlankDefenseClawRule = (): DefenseClawRuleFormValue => ({
  id: '',
  pattern: '',
  title: '',
  severity: 'HIGH',
  confidence: 0.99,
  tags: [],
});

const severityOptions = DEFENSECLAW_SEVERITIES.map((severity) => ({
  value: severity,
  label: severity,
}));

export const DefenseClawRulePackForm = ({
  form,
}: EvaluatorFormProps<DefenseClawRulePackFormValues>) => (
  <Stack gap="md">
    <Divider label="Rules" labelPosition="left" />

    {form.values.rules.map((rule, index) => (
      <Paper key={index} withBorder p="md" radius="sm">
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={600} size="sm">
              Rule {index + 1}
            </Text>
            <ActionIcon
              aria-label={`Remove rule ${index + 1}`}
              data-testid={`defenseclaw-remove-rule-${index}`}
              type="button"
              color="red"
              variant="subtle"
              disabled={form.values.rules.length === 1}
              onClick={() => form.removeListItem('rules', index)}
            >
              <IconTrash size={16} />
            </ActionIcon>
          </Group>

          <TextInput
            label="Rule ID"
            placeholder="AC-CMD-RM-RF"
            required
            {...form.getInputProps(`rules.${index}.id`)}
          />
          <TextInput
            label="Title"
            placeholder="Recursive deletion"
            required
            {...form.getInputProps(`rules.${index}.title`)}
          />
          <Textarea
            label="Pattern"
            placeholder="Enter the DefenseClaw pattern"
            required
            minRows={3}
            autosize
            styles={{ input: { fontFamily: 'monospace' } }}
            {...form.getInputProps(`rules.${index}.pattern`)}
          />
          <Group grow align="flex-start">
            <Select
              label="Severity"
              data={severityOptions}
              allowDeselect={false}
              required
              {...form.getInputProps(`rules.${index}.severity`)}
            />
            <NumberInput
              label="Confidence"
              min={0}
              max={1}
              step={0.01}
              decimalScale={2}
              required
              {...form.getInputProps(`rules.${index}.confidence`)}
            />
          </Group>
          <TagsInput
            label="Tags"
            placeholder="Type a tag and press Enter"
            clearable
            {...form.getInputProps(`rules.${index}.tags`)}
          />
        </Stack>
      </Paper>
    ))}

    {form.errors.rules ? (
      <Text c="red" size="sm" role="alert">
        {String(form.errors.rules)}
      </Text>
    ) : null}

    <Box>
      <Button
        data-testid="defenseclaw-add-rule"
        type="button"
        variant="secondary"
        onClick={() =>
          form.insertListItem('rules', createBlankDefenseClawRule())
        }
      >
        Add rule
      </Button>
    </Box>
  </Stack>
);
