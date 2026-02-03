import {
  Anchor,
  Box,
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
import { modals } from "@mantine/modals";
import { Button } from "@rungalileo/jupiter-ds";
import { IconExternalLink } from "@tabler/icons-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { isApiError } from "@/core/api/errors";
import type { Control, ProblemDetail } from "@/core/api/types";
import { getEvaluator } from "@/core/evaluators";
import { useAddControlToAgent } from "@/core/hooks/query-hooks/use-add-control-to-agent";
import { useUpdateControl } from "@/core/hooks/query-hooks/use-update-control";

import { ApiErrorAlert } from "./api-error-alert";
import { ControlDefinitionForm } from "./control-definition-form";
import { EvaluatorJsonView } from "./evaluator-json-view";
import type {
  ConfigViewMode,
  ControlDefinitionFormValues,
  EditControlMode,
  JsonViewMode,
} from "./types";
import { applyApiErrorsToForms } from "./utils";

const EVALUATOR_CONFIG_HEIGHT = 450;

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
      step_name_mode: "names",
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
      const stepNamesValue = (scope.step_names ?? []).join(", ");
      const stepRegexValue = scope.step_name_regex ?? "";
      const stepNameMode =
        stepRegexValue && !stepNamesValue ? "regex" : "names";
      definitionForm.setValues({
        name: control.name,
        enabled: control.control.enabled,
        step_types: scope.step_types ?? [],
        stages: scope.stages ?? [],
        step_names: stepNamesValue,
        step_name_regex: stepRegexValue,
        step_name_mode: stepNameMode,
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
    const isRegexMode = values.step_name_mode === "regex";

    const definition = {
      ...control.control,
      enabled: values.enabled,
      execution: values.execution,
      scope: {
        step_types: stepTypes.length > 0 ? stepTypes : undefined,
        step_names: !isRegexMode && stepNames.length > 0 ? stepNames : undefined,
        step_name_regex: isRegexMode ? stepNameRegex || undefined : undefined,
        stages: values.stages.length > 0 ? values.stages : undefined,
      },
      selector: { ...control.control.selector, path: values.selector_path },
      action: { decision: values.action_decision },
      evaluator: { ...control.control.evaluator, config: finalConfig },
    };

    const runSave = async () => {
      try {
        if (isCreating) {
          await addControlToAgent.mutateAsync({
            agentId,
            controlName: values.name,
            definition,
          });
        } else {
          await updateControl.mutateAsync({
            agentId,
            controlId: control.id,
            definition,
          });
        }
        // Call onSuccess first (which should close all modals)
        // Only call onClose if onSuccess is not provided (for backward compatibility)
        if (onSuccess) {
          onSuccess();
        } else {
          onClose();
        }
      } catch (error) {
        if (isApiError(error)) {
          const problemDetail = error.problemDetail;
          
          // Check if this is a "name already exists" error (409 Conflict or similar)
          // and map it to the name field if it's not already in the errors array
          const isNameExistsError = 
            (problemDetail.status === 409 || 
             problemDetail.error_code === "CONTROL_NAME_EXISTS" ||
             (problemDetail.detail?.toLowerCase().includes("name") && 
              problemDetail.detail?.toLowerCase().includes("already exists"))) &&
            !problemDetail.errors?.some(e => e.field === "name");

          if (isNameExistsError) {
            // Set error directly on the name field
            definitionForm.setFieldError("name", problemDetail.detail || "Control name already exists");
            // Don't show it in the alert since it's now on the field
            setApiError(null);
            setUnmappedErrors([]);
          } else {
            setApiError(problemDetail);

            if (problemDetail.errors) {
              if (configViewMode === "form") {
                const unmapped = applyApiErrorsToForms(
                  problemDetail.errors,
                  definitionForm,
                  evaluatorForm
                );
                setUnmappedErrors(
                  unmapped.map((e) => ({ field: e.field, message: e.message }))
                );
              } else {
                setUnmappedErrors(
                  problemDetail.errors.map((e) => ({
                    field: e.field,
                    message: e.message,
                  }))
                );
              }
            }
          }
        } else {
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

    modals.openConfirmModal({
      title: isCreating ? "Create control?" : "Save changes?",
      children: (
        <Text size="sm" c="dimmed">
          {isCreating
            ? "This will add the new control to the agent."
            : "This will update the control configuration."}
        </Text>
      ),
      labels: { confirm: "Confirm", cancel: "Cancel" },
      confirmProps: {
        variant: "filled",
        color: "violet",
        size: "sm",
        className: "confirm-modal-confirm-btn",
      },
      cancelProps: { variant: "default", size: "sm" },
      onConfirm: runSave,
    });
  };

  // Render the evaluator's form component
  const FormComponent = evaluator?.FormComponent;

  return (
    <Box>
      <form onSubmit={definitionForm.onSubmit(handleSubmit)}>
        <TextInput
          label="Control name"
          placeholder="Enter control name"
          mb="lg"
          size="sm"
          required
          {...definitionForm.getInputProps("name")}
        />

        <Grid gutter="xl">
          <Grid.Col span={4}>
            <ControlDefinitionForm form={definitionForm} />
          </Grid.Col>

          <Grid.Col span={8}>
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
                    { value: "form", label: "Form" },
                    { value: "json", label: "JSON" },
                  ]}
                  size="xs"
                />
              </Group>

              <Paper withBorder radius="sm" p={16}>
                {configViewMode === "form" && (
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
                        height={EVALUATOR_CONFIG_HEIGHT}
                      />
                    )}
              </Paper>
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

        {/* Buttons */}
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
            Save
          </Button>
        </Group>
      </form>
    </Box>
  );
};
