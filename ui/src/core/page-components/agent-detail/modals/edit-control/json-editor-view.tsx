import { Box, Text, Textarea } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useEffect, useRef } from 'react';

import { isApiError } from '@/core/api/errors';
import {
  labelPropsInline,
  LabelWithTooltip,
} from '@/core/components/label-with-tooltip';

import { ApiErrorAlert } from './api-error-alert';
import type { JsonEditorViewProps } from './types';

const DEFAULT_HEIGHT = 400;
const DEFAULT_VALIDATE_DEBOUNCE_MS = 500;
const DEFAULT_LABEL = 'Configuration (JSON)';
const DEFAULT_TOOLTIP = 'Raw JSON configuration';
const DEFAULT_TEST_ID = 'raw-json-textarea';

export const JsonEditorView = ({
  jsonText,
  handleJsonChange,
  jsonError,
  setJsonError,
  validationError,
  setValidationError,
  onValidateConfig,
  onValidationStatusChange,
  validateDebounceMs = DEFAULT_VALIDATE_DEBOUNCE_MS,
  height = DEFAULT_HEIGHT,
  label = DEFAULT_LABEL,
  tooltip = DEFAULT_TOOLTIP,
  helperText,
  testId = DEFAULT_TEST_ID,
}: JsonEditorViewProps) => {
  const [debouncedJsonText] = useDebouncedValue(jsonText, validateDebounceMs);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!onValidateConfig) return;
    if (!debouncedJsonText) {
      setJsonError?.(null);
      setValidationError?.(null);
      onValidationStatusChange?.('idle');
      return;
    }

    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(debouncedJsonText) as Record<string, unknown>;
    } catch {
      setJsonError?.('Invalid JSON');
      setValidationError?.(null);
      onValidationStatusChange?.('invalid');
      return;
    }

    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setJsonError?.(null);
    onValidationStatusChange?.('validating');
    onValidateConfig(parsed, { signal: controller.signal })
      .then(() => {
        setValidationError?.(null);
        onValidationStatusChange?.('valid');
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        if (isApiError(error)) {
          setValidationError?.(error.problemDetail);
          onValidationStatusChange?.('invalid');
        } else {
          setJsonError?.('Validation failed.');
          setValidationError?.(null);
          onValidationStatusChange?.('invalid');
        }
      });

    return () => controller.abort();
  }, [
    debouncedJsonText,
    onValidateConfig,
    onValidationStatusChange,
    setJsonError,
    setValidationError,
  ]);

  return (
    <Box>
      <Textarea
        label={<LabelWithTooltip label={label} tooltip={tooltip} />}
        labelProps={labelPropsInline}
        value={jsonText}
        onChange={(e) => handleJsonChange(e.currentTarget.value)}
        styles={{
          input: {
            fontFamily: 'monospace',
            fontSize: 12,
            height,
            overflow: 'auto',
          },
        }}
        error={jsonError}
        data-testid={testId}
      />
      {helperText ? (
        <Text size="xs" c="dimmed" mt="xs">
          {helperText}
        </Text>
      ) : null}
      {validationError ? (
        <Box mt="sm">
          <ApiErrorAlert error={validationError} unmappedErrors={[]} />
        </Box>
      ) : null}
    </Box>
  );
};
