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

import { EvaluatorJsonView } from './evaluator-json-view';
import type { ConfigViewMode } from './types';

const DEFAULT_HEIGHT = 450;
type ValidationStatus = 'idle' | 'validating' | 'valid' | 'invalid';

type EvaluatorConfigSectionProps = {
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
  evaluatorForm: UseFormReturnType<any>;
  formComponent?: React.ComponentType<{ form: UseFormReturnType<any> }>;
  height?: number;
};

export function EvaluatorConfigSection({
  config,
  onValidateConfig,
  evaluatorForm,
  formComponent: FormComponent,
  height = DEFAULT_HEIGHT,
}: EvaluatorConfigSectionProps) {
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

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Group gap="xs">
          <Text size="sm" fw={500}>
            Evaluator configuration
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
      {statusLabel ? (
        <Text size="xs" c={statusColor}>
          {statusLabel}
        </Text>
      ) : null}

      <Paper withBorder radius="sm" p={16}>
        {configViewMode === 'form' && (
          <ScrollArea h={height} type="auto">
            {FormComponent ? (
              <FormComponent form={evaluatorForm} />
            ) : (
              <Text c="dimmed" ta="center" py="xl">
                No form available for this evaluator. Use JSON view to
                configure.
              </Text>
            )}
          </ScrollArea>
        )}

        {configViewMode === 'json' && (
          <EvaluatorJsonView
            onValidateConfig={onValidateConfig}
            onValidationStatusChange={setValidationStatus}
            height={height}
            {...jsonViewProps}
          />
        )}
      </Paper>
    </Stack>
  );
}
