import { Box, Textarea } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useEffect, useRef } from 'react';

import { isApiError } from '@/core/api/errors';

import { ApiErrorAlert } from './api-error-alert';
import type { EvaluatorJsonViewProps } from './types';

const DEFAULT_HEIGHT = 400;
const DEFAULT_VALIDATE_DEBOUNCE_MS = 500;

export const EvaluatorJsonView = ({
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
}: EvaluatorJsonViewProps) => {
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
      parsed = JSON.parse(debouncedJsonText);
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
    setJsonError,
    onValidateConfig,
    setValidationError,
    onValidationStatusChange,
  ]);

  return (
    <Box>
      <Textarea
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
        data-testid="raw-json-textarea"
      />
      {validationError ? (
        <Box mt="sm">
          <ApiErrorAlert error={validationError} unmappedErrors={[]} />
        </Box>
      ) : null}
    </Box>
  );
};
