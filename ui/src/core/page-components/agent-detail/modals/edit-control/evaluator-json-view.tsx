import {
  Box,
  // Group,
  ScrollArea,
  // SegmentedControl,
  Textarea,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { useEffect } from "react";

import { JsonEditor } from "@/components/json-editor";
import { isApiError } from "@/core/api/errors";

import { ApiErrorAlert } from "./api-error-alert";
import type { EvaluatorJsonViewProps } from "./types";

const DEFAULT_HEIGHT = 400;

export const EvaluatorJsonView = ({
  config,
  onChange,
  jsonViewMode,
  onJsonViewModeChange: _onJsonViewModeChange,
  rawJsonText,
  onRawJsonTextChange,
  rawJsonError,
  onRawJsonErrorChange,
  validationError,
  onValidationErrorChange,
  onValidateConfig,
  onValidationStatusChange,
  validateDebounceMs = 500,
  height = DEFAULT_HEIGHT,
}: EvaluatorJsonViewProps) => {
  const [debouncedRawJsonText] = useDebouncedValue(rawJsonText, validateDebounceMs);

  useEffect(() => {
    if (!onValidateConfig) return;
    if (!debouncedRawJsonText) {
      onRawJsonErrorChange?.(null);
      onValidationErrorChange?.(null);
      onValidationStatusChange?.("idle");
      return;
    }

    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(debouncedRawJsonText);
    } catch {
      onRawJsonErrorChange?.("Invalid JSON");
      onValidationErrorChange?.(null);
      onValidationStatusChange?.("invalid");
      return;
    }

    onRawJsonErrorChange?.(null);
    onValidationStatusChange?.("validating");
    onValidateConfig(parsed)
      .then(() => {
        onValidationErrorChange?.(null);
        onValidationStatusChange?.("valid");
      })
      .catch((error) => {
        if (isApiError(error)) {
          onValidationErrorChange?.(error.problemDetail);
          onValidationStatusChange?.("invalid");
        } else {
          onRawJsonErrorChange?.("Validation failed.");
          onValidationErrorChange?.(null);
          onValidationStatusChange?.("invalid");
        }
      });
  }, [
    debouncedRawJsonText,
    onRawJsonErrorChange,
    onValidateConfig,
    onValidationErrorChange,
    onValidationStatusChange,
  ]);
  // TODO: Re-enable tree/raw toggle when needed
  // <Group justify='flex-end'>
  //   <SegmentedControl
  //     value={jsonViewMode}
  //     onChange={handleModeChange}
  //     data={[
  //       { value: "tree", label: "Tree" },
  //       { value: "raw", label: "Raw" },
  //     ]}
  //     size='xs'
  //   />
  // </Group>

  if (jsonViewMode === "tree") {
    return (
      <ScrollArea h={height} type="auto">
        <Box p="xs">
          <JsonEditor
            data={config}
            setData={onChange}
            rootName="config"
            restrictEdit={false}
            restrictDelete={false}
            restrictAdd={false}
            collapse={false}
            rootFontSize={12}
          />
        </Box>
      </ScrollArea>
    );
  }

  return (
    <Box>
      <Textarea
        value={rawJsonText}
        onChange={(e) => onRawJsonTextChange(e.currentTarget.value)}
        styles={{
          input: {
            fontFamily: "monospace",
            fontSize: 12,
            height,
            overflow: "auto",
          },
        }}
        error={rawJsonError}
        data-testid="raw-json-textarea"
      />
      {validationError && (
        <Box mt="sm">
          <ApiErrorAlert
            error={validationError}
            unmappedErrors={[]}
          />
        </Box>
      )}
    </Box>
  );
};
