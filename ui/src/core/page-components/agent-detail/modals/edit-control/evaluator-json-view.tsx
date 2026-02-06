import { Box, Textarea } from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { useEffect } from "react";

import { isApiError } from "@/core/api/errors";

import { ApiErrorAlert } from "./api-error-alert";
import type { EvaluatorJsonViewProps } from "./types";

const DEFAULT_HEIGHT = 400;

export const EvaluatorJsonView = ({
  jsonText,
  handleJsonChange,
  jsonError,
  setJsonError,
  validationError,
  setValidationError,
  onValidateConfig,
  onValidationStatusChange,
  validateDebounceMs = 500,
  height = DEFAULT_HEIGHT,
}: EvaluatorJsonViewProps) => {
  const [debouncedJsonText] = useDebouncedValue(jsonText, validateDebounceMs);

  useEffect(() => {
    if (!onValidateConfig) return;
    if (!debouncedJsonText) {
      setJsonError?.(null);
      setValidationError?.(null);
      onValidationStatusChange?.("idle");
      return;
    }

    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(debouncedJsonText);
    } catch {
      setJsonError?.("Invalid JSON");
      setValidationError?.(null);
      onValidationStatusChange?.("invalid");
      return;
    }

    setJsonError?.(null);
    onValidationStatusChange?.("validating");
    onValidateConfig(parsed)
      .then(() => {
        setValidationError?.(null);
        onValidationStatusChange?.("valid");
      })
      .catch((error) => {
        if (isApiError(error)) {
          setValidationError?.(error.problemDetail);
          onValidationStatusChange?.("invalid");
        } else {
          setJsonError?.("Validation failed.");
          setValidationError?.(null);
          onValidationStatusChange?.("invalid");
        }
      });
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
            fontFamily: "monospace",
            fontSize: 12,
            height,
            overflow: "auto",
          },
        }}
        error={jsonError}
        data-testid='raw-json-textarea'
      />
      {validationError ? <Box mt='sm'>
          <ApiErrorAlert error={validationError} unmappedErrors={[]} />
        </Box> : null}
    </Box>
  );
};
