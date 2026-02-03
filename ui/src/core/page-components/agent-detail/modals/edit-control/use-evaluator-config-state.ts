import { useCallback, useMemo, useState } from "react";

import type { ProblemDetail } from "@/core/api/types";

import type { ConfigViewMode, JsonViewMode } from "./types";

export interface UseEvaluatorConfigStateArgs {
  getConfigFromForm: () => Record<string, unknown>;
  onConfigChange: (config: Record<string, unknown>) => void;
  onValidateConfig: (config: Record<string, unknown>) => Promise<void>;
}

export interface EvaluatorConfigState {
  getConfigFromForm: () => Record<string, unknown>;
  configViewMode: ConfigViewMode;
  jsonViewMode: JsonViewMode;
  rawJsonText: string;
  rawJsonError: string | null;
  validationError: ProblemDetail | null;
  setRawJsonText: (value: string) => void;
  setRawJsonError: (error: string | null) => void;
  setValidationError: (error: ProblemDetail | null) => void;
  setJsonViewMode: (mode: JsonViewMode) => void;
  setConfigViewMode: (mode: ConfigViewMode) => void;
  handleConfigViewModeChange: (value: string) => Promise<void>;
  handleRawJsonChange: (value: string) => void;
  getJsonConfig: () => Record<string, unknown> | null;
  isJsonInvalid: boolean;
  reset: () => void;
}

export function useEvaluatorConfigState({
  getConfigFromForm,
  onConfigChange,
  onValidateConfig,
}: UseEvaluatorConfigStateArgs): EvaluatorConfigState {
  const [configViewMode, setConfigViewMode] = useState<ConfigViewMode>("form");
  const [jsonViewMode, setJsonViewMode] = useState<JsonViewMode>("raw");
  const [rawJsonText, setRawJsonText] = useState("");
  const [rawJsonError, setRawJsonError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<ProblemDetail | null>(null);

  const reset = useCallback(() => {
    setConfigViewMode("form");
    setJsonViewMode("raw");
    setRawJsonText("");
    setRawJsonError(null);
    setValidationError(null);
  }, []);

  const handleRawJsonChange = useCallback((value: string) => {
    setRawJsonText(value);
    setValidationError(null);
  }, []);

  const getJsonConfig = useCallback(() => {
    try {
      return JSON.parse(rawJsonText || "{}");
    } catch {
      setRawJsonError("Invalid JSON. Please fix before saving.");
      return null;
    }
  }, [rawJsonText]);

  const handleConfigViewModeChange = useCallback(
    async (value: string) => {
      if (value === "json" && configViewMode === "form") {
        setRawJsonText(JSON.stringify(getConfigFromForm(), null, 2));
        setRawJsonError(null);
        setConfigViewMode(value as ConfigViewMode);
        return;
      }

      if (value === "form" && configViewMode === "json") {
        let finalConfig: Record<string, unknown>;
        try {
          finalConfig = JSON.parse(rawJsonText || "{}");
        } catch {
          setRawJsonError("Invalid JSON. Please fix before switching to form.");
          setValidationError(null);
          return;
        }

        try {
          await onValidateConfig(finalConfig);
          setRawJsonError(null);
          setValidationError(null);
        } catch (error) {
          if (error && typeof error === "object" && "problemDetail" in error) {
            setValidationError(
              (error as { problemDetail: ProblemDetail }).problemDetail
            );
            setRawJsonError(null);
          } else {
            setRawJsonError("Validation failed.");
            setValidationError(null);
          }
          return;
        }

        onConfigChange(finalConfig);
        setConfigViewMode(value as ConfigViewMode);
      }
    },
    [configViewMode, getConfigFromForm, onConfigChange, onValidateConfig, rawJsonText]
  );

  const isJsonInvalid = useMemo(() => {
    if (configViewMode !== "json") return false;
    return rawJsonError !== null || validationError !== null;
  }, [configViewMode, rawJsonError, validationError]);

  return {
    getConfigFromForm,
    configViewMode,
    jsonViewMode,
    rawJsonText,
    rawJsonError,
    validationError,
    setRawJsonText,
    setRawJsonError,
    setValidationError,
    setJsonViewMode,
    setConfigViewMode,
    handleConfigViewModeChange,
    handleRawJsonChange,
    getJsonConfig,
    isJsonInvalid,
    reset,
  };
}
