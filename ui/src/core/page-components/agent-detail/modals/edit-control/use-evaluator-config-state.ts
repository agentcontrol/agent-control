import { useCallback, useMemo, useState } from 'react';

import type { ProblemDetail } from '@/core/api/types';

import type { ConfigViewMode } from './types';

export type UseEvaluatorConfigStateArgs = {
  getConfigFromForm: () => Record<string, unknown>;
  onConfigChange: (config: Record<string, unknown>) => void;
  onValidateConfig: (
    config: Record<string, unknown>,
    options?: { signal?: AbortSignal }
  ) => Promise<void>;
};

export type EvaluatorConfigState = {
  getConfigFromForm: () => Record<string, unknown>;
  configViewMode: ConfigViewMode;
  jsonText: string;
  jsonError: string | null;
  validationError: ProblemDetail | null;
  setJsonText: (value: string) => void;
  setJsonError: (error: string | null) => void;
  setValidationError: (error: ProblemDetail | null) => void;
  setConfigViewMode: (mode: ConfigViewMode) => void;
  handleConfigViewModeChange: (value: string) => Promise<void>;
  handleJsonChange: (value: string) => void;
  getJsonConfig: () => Record<string, unknown> | null;
  isJsonInvalid: boolean;
  reset: () => void;
};

export function useEvaluatorConfigState({
  getConfigFromForm,
  onConfigChange,
  onValidateConfig,
}: UseEvaluatorConfigStateArgs): EvaluatorConfigState {
  const [configViewMode, setConfigViewMode] = useState<ConfigViewMode>('form');
  const [jsonText, setJsonText] = useState('');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<ProblemDetail | null>(
    null
  );

  const reset = useCallback(() => {
    setConfigViewMode('form');
    setJsonText('');
    setJsonError(null);
    setValidationError(null);
  }, []);

  const handleJsonChange = useCallback((value: string) => {
    setJsonText(value);
    setValidationError(null);
  }, []);

  const getJsonConfig = useCallback(() => {
    try {
      return JSON.parse(jsonText || '{}');
    } catch {
      setJsonError('Invalid JSON. Please fix before saving.');
      return null;
    }
  }, [jsonText]);

  const handleConfigViewModeChange = useCallback(
    async (value: string) => {
      const mode = value as ConfigViewMode;

      if (mode === 'json') {
        setJsonText(JSON.stringify(getConfigFromForm(), null, 2));
        setJsonError(null);
        setConfigViewMode(mode);
        return;
      }

      if (mode === 'form') {
        let finalConfig: Record<string, unknown>;
        try {
          finalConfig = JSON.parse(jsonText || '{}');
        } catch {
          setJsonError('Invalid JSON. Please fix before switching to form.');
          setValidationError(null);
          return;
        }

        try {
          await onValidateConfig(finalConfig);
          setJsonError(null);
          setValidationError(null);
        } catch (error) {
          if (error && typeof error === 'object' && 'problemDetail' in error) {
            setValidationError(
              (error as { problemDetail: ProblemDetail }).problemDetail
            );
            setJsonError(null);
          } else {
            setJsonError('Validation failed.');
            setValidationError(null);
          }
          return;
        }

        onConfigChange(finalConfig);
        setConfigViewMode(mode);
      }
    },
    [getConfigFromForm, onConfigChange, onValidateConfig, jsonText]
  );

  const isJsonInvalid = useMemo(() => {
    if (configViewMode !== 'json') return false;
    return jsonError !== null || validationError !== null;
  }, [configViewMode, jsonError, validationError]);

  return {
    getConfigFromForm,
    configViewMode,
    jsonText,
    jsonError,
    validationError,
    setJsonText,
    setJsonError,
    setValidationError,
    setConfigViewMode,
    handleConfigViewModeChange,
    handleJsonChange,
    getJsonConfig,
    isJsonInvalid,
    reset,
  };
}
