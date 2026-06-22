import {
  Anchor,
  Group,
  Paper,
  ScrollArea,
  SegmentedControl,
  Stack,
  Text,
} from '@mantine/core';
import type { UseFormReturnType } from '@mantine/form';
import { IconExternalLink } from '@tabler/icons-react';
import { useState } from 'react';

import type { ProblemDetail } from '@/core/api/types';

import { JsonEditorView } from './json-editor-view';
import type { ConfigViewMode } from './types';
import type { JsonSchema } from './types';

const DEFAULT_HEIGHT = 450;
const CONTENT_MIN_HEIGHT_EXTRA = 60;
type ValidationStatus = 'idle' | 'validating' | 'valid' | 'invalid';

type RuleConfigSectionProps = {
  config: {
    configViewMode: ConfigViewMode;
    jsonText: string;
    jsonError: string | null;
    validationError: ProblemDetail | null;
    handleConfigViewModeChange: (value: string) => Promise<void>;
    handleJsonChange: (value: string) => void;
    setJsonError: (error: string | null) => void;
    setValidationError: (error: ProblemDetail | null) => void;
  };
  onValidateConfig: (
    config: Record<string, unknown>,
    options?: { signal?: AbortSignal }
  ) => Promise<void>;
  onConfigChange: (config: Record<string, unknown>) => void;
  ruleForm: UseFormReturnType<any>;
  formComponent?: React.ComponentType<{ form: UseFormReturnType<any> }>;
  height?: number;
  activeRuleId?: string;
  activeRuleSchema?: JsonSchema | null;
};

export function RuleConfigSection({
  config,
  onValidateConfig,
  ruleForm,
  formComponent: FormComponent,
  height = DEFAULT_HEIGHT,
  activeRuleId,
  activeRuleSchema,
}: RuleConfigSectionProps) {
  const [validationStatus, setValidationStatus] =
    useState<ValidationStatus>('idle');

  const {
    configViewMode,
    handleConfigViewModeChange,
    jsonError,
    ...jsonViewProps
  } = config;

  const statusLabel = (() => {
    if (configViewMode !== 'json') return null;
    if (validationStatus === 'validating') return 'Validating...';
    if (validationStatus === 'valid') return 'JSON valid';
    if (validationStatus === 'invalid') return 'JSON invalid';
    return null;
  })();

  const statusColor =
    validationStatus === 'valid'
      ? 'green'
      : validationStatus === 'invalid'
        ? 'red'
        : 'dimmed';

  const contentHeight = height + CONTENT_MIN_HEIGHT_EXTRA;

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Group gap="xs">
          <Text size="sm" fw={500}>
            Rule configuration
          </Text>
          <Anchor
            href="https://github.com/agentcontrol/agent-control/blob/main/README.md"
            target="_blank"
            size="xs"
            c="blue"
            underline="never"
          >
            <Group gap={2} align="center">
              Docs <IconExternalLink size={12} />
            </Group>
          </Anchor>
        </Group>
        <Group gap="xs" align="center">
          {statusLabel ? (
            <Text size="xs" c={statusColor}>
              {statusLabel}
            </Text>
          ) : null}
          <SegmentedControl
            value={configViewMode}
            onChange={handleConfigViewModeChange}
            disabled={configViewMode === 'json' && !!jsonError}
            data={[
              { value: 'form', label: 'Form' },
              { value: 'json', label: 'JSON' },
            ]}
            size="xs"
          />
        </Group>
      </Group>
      <Paper withBorder radius="sm" p={16}>
        <ScrollArea h={contentHeight} type="always" offsetScrollbars="y">
          {configViewMode === 'form' ? (
            FormComponent ? (
              <FormComponent form={ruleForm} />
            ) : (
              <Text c="dimmed" ta="center" py="xl">
                No form available for this rule. Use JSON view to
                configure.
              </Text>
            )
          ) : (
            <JsonEditorView
              onValidateConfig={onValidateConfig}
              onValidationStatusChange={setValidationStatus}
              height={height}
              label="Configuration (JSON)"
              tooltip="Raw rule configuration in JSON format"
              testId="raw-json-textarea"
              editorMode="rule-config"
              activeRuleId={activeRuleId}
              schema={activeRuleSchema}
              {...jsonViewProps}
            />
          )}
        </ScrollArea>
      </Paper>
    </Stack>
  );
}
