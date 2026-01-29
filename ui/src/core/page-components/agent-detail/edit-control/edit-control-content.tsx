import {
  Anchor,
  Divider,
  Grid,
  Group,
  Paper,
  ScrollArea,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { Button } from "@rungalileo/jupiter-ds";
import { IconExternalLink } from "@tabler/icons-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { isApiError } from "@/core/api/errors";
import type { Control, ProblemDetail } from "@/core/api/types";
import { useAddControlToAgent } from "@/core/hooks/query-hooks/use-add-control-to-agent";
import { useUpdateControl } from "@/core/hooks/query-hooks/use-update-control";

import { ApiErrorAlert } from "./api-error-alert";
import { ControlDefinitionForm } from "./control-definition-form";
import { EvaluatorJsonView } from "./evaluator-json-view";
import { getEvaluator } from "./evaluators";
import type {
  ConfigViewMode,
  ControlDefinitionFormValues,
  EditControlMode,
  JsonViewMode,
} from "./types";
import { applyApiErrorsToForms } from "./utils";

const EVALUATOR_CONFIG_HEIGHT = 400;

export interface EditControlContentProps {
  /** The control to edit/create template */
  control: Control;
  /** Agent ID for invalidating queries on save */
  agentId: string;
  /** Mode: 'create' for new control, 'edit' for existing */
  mode?: EditControlMode;
  /** Callback when modal is closed */
  onClose: () => void;
  /** Callback when save succeeds */
  onSuccess?: () => void;
}

export const EditControlContent = ({
  control,
  agentId,
  mode = "edit",
  onClose,
  onSuccess,
}: EditControlContentProps) => {
  // View mode state
  const [configViewMode, setConfigViewMode] = useState<ConfigViewMode>("form");
  // TODO: Tree view disabled for now, defaulting to "raw"
  const [jsonViewMode, setJsonViewMode] = useState<JsonViewMode>("raw");
  const [rawJsonText, setRawJsonText] = useState("");
  const [rawJsonError, setRawJsonError] = useState<string | null>(null);

  // API error state
  const [apiError, setApiError] = useState<ProblemDetail | null>(null);
  // Errors that couldn't be mapped to form fields (shown in Alert)
  const [unmappedErrors, setUnmappedErrors] = useState<
    Array<{ field: string | null; message: string }>
  >([]);

  // Mutation hooks
  const updateControl = useUpdateControl();
  const addControlToAgent = useAddControlToAgent();
  const isCreating = mode === "create";
  const isPending = isCreating
    ? addControlToAgent.isPending
    : updateControl.isPending;

  // Track which evaluator the evaluator form has been initialized for
  const formInitializedForEvaluator = useRef<string>("");

  // Get evaluator for this control
  const evaluatorId = control.control.evaluator.name || "";
  const evaluator = useMemo(() => getEvaluator(evaluatorId), [evaluatorId]);

  // Control definition form
  const definitionForm = useForm<ControlDefinitionFormValues>({
    initialValues: {
      name: "",
      enabled: true,
      step_types: ["llm"],
      stages: ["post"],
      step_names: "",
      step_name_regex: "",
      selector_path: "*",
      action_decision: "deny",
      execution: "server",
    },
    validate: {
      name: (value) => (!value?.trim() ? "Control name is required" : null),
      selector_path: (value) =>
        !value?.trim() ? "Selector path is required" : null,
    },
  });

  // Evaluator config form - dynamically configured based on evaluator
  const evaluatorForm = useForm({
    initialValues: evaluator?.initialValues ?? {},
    validate: evaluator?.validate,
  });

  // Get config from evaluator form
  // If form hasn't been initialized for current evaluator yet, use initial values to avoid crashes
  const getEvaluatorConfig = () => {
    if (!evaluator) return {};
    if (formInitializedForEvaluator.current !== evaluatorId) {
      return evaluator.toConfig(evaluator.initialValues);
    }
    return evaluator.toConfig(evaluatorForm.values);
  };

  // Sync form to JSON
  const syncFormToJson = () => {
    setRawJsonText(JSON.stringify(getEvaluatorConfig(), null, 2));
    setRawJsonError(null);
  };

  // Sync JSON to form
  const syncJsonToForm = (config: Record<string, unknown>) => {
    if (evaluator) {
      evaluatorForm.setValues(evaluator.fromConfig(config));
    }
  };

  // Handle config view mode changes
  const handleConfigViewModeChange = (value: string) => {
    if (value === "json" && configViewMode === "form") {
      syncFormToJson();
    } else if (value === "form" && configViewMode === "json") {
      if (jsonViewMode === "raw" && rawJsonText) {
        try {
          syncJsonToForm(JSON.parse(rawJsonText));
          setRawJsonError(null);
        } catch {
          setRawJsonError("Invalid JSON. Please fix before switching to form.");
          return;
        }
      }
    }
    setConfigViewMode(value as ConfigViewMode);
  };

  // Handle JSON view mode changes
  const handleJsonViewModeChange = (mode: JsonViewMode) => {
    if (mode === "raw" && jsonViewMode === "tree") {
      syncFormToJson();
    } else if (mode === "tree" && jsonViewMode === "raw") {
      try {
        syncJsonToForm(JSON.parse(rawJsonText));
        setRawJsonError(null);
      } catch {
        setRawJsonError("Invalid JSON. Please fix before switching views.");
        return;
      }
    }
    setJsonViewMode(mode);
  };

  // Handle raw JSON changes
  const handleRawJsonChange = (value: string) => {
    setRawJsonText(value);
    try {
      JSON.parse(value);
      setRawJsonError(null);
    } catch {
      setRawJsonError("Invalid JSON");
    }
  };

  // Reset view mode and errors when evaluator changes
  useEffect(() => {
    setConfigViewMode("form");
    setJsonViewMode("raw"); // TODO: Change to "tree" when re-enabling tree view
    setRawJsonText("");
    setRawJsonError(null);
    setApiError(null);
    setUnmappedErrors([]);
  }, [evaluatorId]);

  // Load control data into forms
  useEffect(() => {
    if (control && evaluator) {
      const scope = control.control.scope ?? {};
      definitionForm.setValues({
        name: control.name,
        enabled: control.control.enabled,
        step_types: scope.step_types ?? [],
        stages: scope.stages ?? [],
        step_names: (scope.step_names ?? []).join(", "),
        step_name_regex: scope.step_name_regex ?? "",
        selector_path: control.control.selector.path ?? "*",
        action_decision: control.control.action.decision,
        execution: control.control.execution ?? "server",
      });
      evaluatorForm.setValues(
        evaluator.fromConfig(control.control.evaluator.config)
      );
      // Mark form as initialized for this evaluator
      formInitializedForEvaluator.current = evaluatorId;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [control, evaluator, evaluatorId]);

  // Handle form submission
  const handleSubmit = async (values: ControlDefinitionFormValues) => {
    // Clear previous errors
    setApiError(null);
    setUnmappedErrors([]);
    definitionForm.clearErrors();
    evaluatorForm.clearErrors();

    let finalConfig: Record<string, unknown>;

    if (configViewMode === "json") {
      try {
        finalConfig = JSON.parse(rawJsonText || "{}");
      } catch {
        setRawJsonError("Invalid JSON. Please fix before saving.");
        return;
      }
    } else {
      // Validate evaluator form
      const validation = evaluatorForm.validate();
      if (validation.hasErrors) return;
      finalConfig = getEvaluatorConfig();
    }

    const stepTypes = values.step_types
      .map((value) => value.trim())
      .filter(Boolean);
    const stepNames = values.step_names
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const stepNameRegex = values.step_name_regex.trim();

    const definition = {
      ...control.control,
      enabled: values.enabled,
      execution: values.execution,
      scope: {
        step_types: stepTypes.length > 0 ? stepTypes : undefined,
        step_names: stepNames.length > 0 ? stepNames : undefined,
        step_name_regex: stepNameRegex || undefined,
        stages: values.stages.length > 0 ? values.stages : undefined,
      },
      selector: { ...control.control.selector, path: values.selector_path },
      action: { decision: values.action_decision },
      evaluator: { ...control.control.evaluator, config: finalConfig },
    };

    try {
      if (isCreating) {
        // Create mode: use addControlToAgent
        await addControlToAgent.mutateAsync({
          agentId,
          controlName: values.name,
          definition,
        });
      } else {
        // Edit mode: use updateControl
        await updateControl.mutateAsync({
          agentId,
          controlId: control.id,
          definition,
        });
      }
      onSuccess?.();
      onClose();
    } catch (error) {
      if (isApiError(error)) {
        const problemDetail = error.problemDetail;
        setApiError(problemDetail);

        if (problemDetail.errors) {
          if (configViewMode === "form") {
            // Apply field-level errors to forms, capture unmapped ones
            const unmapped = applyApiErrorsToForms(
              problemDetail.errors,
              definitionForm,
              evaluatorForm
            );
            setUnmappedErrors(
              unmapped.map((e) => ({ field: e.field, message: e.message }))
            );
          } else {
            // In JSON view, show all errors in the main alert
            setUnmappedErrors(
              problemDetail.errors.map((e) => ({
                field: e.field,
                message: e.message,
              }))
            );
          }
        }
      } else {
        // Unexpected error
        setApiError({
          type: "about:blank",
          title: "Error",
          status: 500,
          detail:
            error instanceof Error
              ? error.message
              : "An unexpected error occurred",
          error_code: "UNKNOWN_ERROR",
          reason: "Unknown",
        });
      }
    }
  };

  // Render the evaluator's form component
  const FormComponent = evaluator?.FormComponent;

  return (
    <form onSubmit={definitionForm.onSubmit(handleSubmit)}>
      <TextInput
        label="Control name"
        placeholder="Enter control name"
        mb="lg"
        size="sm"
        {...definitionForm.getInputProps("name")}
      />

      <Grid gutter="xl">
        <Grid.Col span={4}>
          <ScrollArea h={EVALUATOR_CONFIG_HEIGHT + 50} type="auto">
            <ControlDefinitionForm form={definitionForm} />
          </ScrollArea>
        </Grid.Col>

        <Grid.Col span={8}>
          <Stack gap="md">
            <Group justify="space-between" align="center">
              <Group gap="xs">
                <Text size="sm" fw={500}>
                  Evaluator configuration
                </Text>
                <Anchor
                  href="https://docs.galileo.ai/controls"
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
                  { value: "form", label: "Form" },
                  { value: "json", label: "JSON" },
                ]}
                size="xs"
              />
            </Group>

            {configViewMode === "form" && (
              <Paper withBorder radius="sm" p={16}>
                <ScrollArea h={EVALUATOR_CONFIG_HEIGHT} type="auto">
                  {FormComponent ? (
                    <FormComponent form={evaluatorForm} />
                  ) : (
                    <Text c="dimmed" ta="center" py="xl">
                      No form available for this evaluator. Use JSON view to
                      configure.
                    </Text>
                  )}
                </ScrollArea>
              </Paper>
            )}

            {configViewMode === "json" && (
              <EvaluatorJsonView
                config={getEvaluatorConfig()}
                onChange={syncJsonToForm}
                jsonViewMode={jsonViewMode}
                onJsonViewModeChange={handleJsonViewModeChange}
                rawJsonText={rawJsonText}
                onRawJsonTextChange={handleRawJsonChange}
                rawJsonError={rawJsonError}
              />
            )}
          </Stack>
        </Grid.Col>
      </Grid>

      {/* API Error Alert */}
      {apiError && (
        <>
          <Divider mt="xl" mb="md" />
          <ApiErrorAlert
            error={apiError}
            unmappedErrors={unmappedErrors}
            onClose={() => setApiError(null)}
          />
        </>
      )}

      <Divider mt="xl" mb="md" />

      <Group justify="flex-end">
        <Button
          variant="outline"
          onClick={onClose}
          type="button"
          data-testid="cancel-button"
        >
          Cancel
        </Button>
        <Button
          variant="filled"
          type="submit"
          data-testid="save-button"
          loading={isPending}
        >
          {isCreating ? "Create" : "Save"}
        </Button>
      </Group>
    </form>
  );
};
