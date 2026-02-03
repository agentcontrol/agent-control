import {
  Anchor,
  Group,
  Paper,
  ScrollArea,
  SegmentedControl,
  Stack,
  Text,
} from "@mantine/core";
import type { UseFormReturnType } from "@mantine/form";
import { IconExternalLink } from "@tabler/icons-react";
import { useState } from "react";

import type { ProblemDetail } from "@/core/api/types";

import { EvaluatorJsonView } from "./evaluator-json-view";
import type { ConfigViewMode, JsonViewMode } from "./types";

const DEFAULT_HEIGHT = 450;
type ValidationStatus = "idle" | "validating" | "valid" | "invalid";

interface EvaluatorConfigSectionProps {
  config: {
    configViewMode: ConfigViewMode;
    jsonViewMode: JsonViewMode;
    rawJsonText: string;
    rawJsonError: string | null;
    validationError: ProblemDetail | null;
    handleConfigViewModeChange: (value: string) => Promise<void>;
    handleRawJsonChange: (value: string) => void;
    setRawJsonError: (error: string | null) => void;
    setValidationError: (error: ProblemDetail | null) => void;
    setJsonViewMode: (mode: JsonViewMode) => void;
    getConfigFromForm: () => Record<string, unknown>;
  };
  onValidateConfig: (config: Record<string, unknown>) => Promise<void>;
  onConfigChange: (config: Record<string, unknown>) => void;
  evaluatorForm: UseFormReturnType<any>;
  formComponent?: React.ComponentType<{ form: UseFormReturnType<any> }>;
  height?: number;
}

export function EvaluatorConfigSection({
  config,
  onConfigChange,
  onValidateConfig,
  evaluatorForm,
  formComponent: FormComponent,
  height = DEFAULT_HEIGHT,
}: EvaluatorConfigSectionProps) {
  const [validationStatus, setValidationStatus] =
    useState<ValidationStatus>("idle");

  const {
    configViewMode,
    jsonViewMode,
    rawJsonText,
    rawJsonError,
    validationError,
    handleConfigViewModeChange,
    handleRawJsonChange,
    setRawJsonError,
    setValidationError,
    setJsonViewMode,
    getConfigFromForm,
  } = config;

  const statusLabel = (() => {
    if (configViewMode !== "json") return null;
    if (validationStatus === "validating") return "Validating...";
    if (validationStatus === "valid") return "JSON valid";
    if (validationStatus === "invalid") return "JSON invalid";
    return null;
  })();

  const statusColor =
    validationStatus === "valid"
      ? "green"
      : validationStatus === "invalid"
        ? "red"
        : "dimmed";

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
          data={[
            {
              value: "form",
              label: "Form",
              disabled: configViewMode === "json" && !!rawJsonError,
            },
            { value: "json", label: "JSON" },
          ]}
          size="xs"
        />
      </Group>
      {statusLabel && (
        <Text size="xs" c={statusColor}>
          {statusLabel}
        </Text>
      )}

      <Paper withBorder radius="sm" p={16}>
        {configViewMode === "form" && (
          <ScrollArea h={height} type="auto">
            {FormComponent ? (
              <FormComponent form={evaluatorForm} />
            ) : (
              <Text c="dimmed" ta="center" py="xl">
                No form available for this evaluator. Use JSON view to configure.
              </Text>
            )}
          </ScrollArea>
        )}

        {configViewMode === "json" && (
          <EvaluatorJsonView
            config={getConfigFromForm()}
            onChange={onConfigChange}
            jsonViewMode={jsonViewMode}
            onJsonViewModeChange={setJsonViewMode}
            rawJsonText={rawJsonText}
            onRawJsonTextChange={handleRawJsonChange}
            rawJsonError={rawJsonError}
            onRawJsonErrorChange={setRawJsonError}
            validationError={validationError}
            onValidationErrorChange={setValidationError}
            onValidateConfig={onValidateConfig}
            onValidationStatusChange={setValidationStatus}
            height={height}
          />
        )}
      </Paper>
    </Stack>
  );
}
