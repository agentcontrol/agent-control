import {
  Anchor,
  Divider,
  Grid,
  Group,
  Modal,
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
import { useEffect, useState } from "react";

import type { Control } from "@/core/api/types";

import { ControlDefinitionForm } from "./control-definition-form";
import { EvaluatorConfigForm } from "./evaluator-forms";
import { EvaluatorJsonView } from "./evaluator-json-view";
import type {
  ConfigViewMode,
  ControlDefinitionFormValues,
  EditControlProps,
  JsonViewMode,
  ListFormValues,
  RegexFormValues,
} from "./types";

export const EditControl = ({
  opened,
  control,
  onClose,
  onSave,
}: EditControlProps) => {
  // View mode state
  const [configViewMode, setConfigViewMode] = useState<ConfigViewMode>("form");
  const [jsonViewMode, setJsonViewMode] = useState<JsonViewMode>("tree");
  const [rawJsonText, setRawJsonText] = useState("");
  const [rawJsonError, setRawJsonError] = useState<string | null>(null);

  // Form state using Mantine useForm
  const form = useForm<ControlDefinitionFormValues>({
    initialValues: {
      name: "",
      enabled: true,
      appliesTo: "llm_call",
      checkStage: "post",
      selectorPath: "*",
      actionDecision: "deny",
      local: false,
    },
    validate: {
      name: (value) => {
        if (!value || value.trim() === "") {
          return "Control name is required";
        }
        return null;
      },
      selectorPath: (value) => {
        if (!value || value.trim() === "") {
          return "Selector path is required";
        }
        return null;
      },
    },
  });

  // Evaluator config forms
  const regexForm = useForm<RegexFormValues>({
    initialValues: {
      pattern: "^.*$",
    },
    validate: {
      pattern: (value) => {
        if (!value || value.trim() === "") {
          return "Pattern is required";
        }
        try {
          new RegExp(value);
          return null;
        } catch (error) {
          return `Invalid regex pattern: ${
            error instanceof Error ? error.message : "Unknown error"
          }`;
        }
      },
    },
  });

  const listForm = useForm<ListFormValues>({
    initialValues: {
      values: "",
      logic: "any",
      matchOn: "match",
      matchMode: "exact",
      caseSensitive: false,
    },
    validate: {
      values: (value) => {
        const trimmedValues = value.split("\n").filter((v) => v.trim() !== "");
        if (trimmedValues.length === 0) {
          return "At least one value is required";
        }
        return null;
      },
    },
  });

  // Get plugin ID from control
  const pluginId = control?.control.evaluator.plugin || "";

  // Helper to get evaluator config from the appropriate form
  const getEvaluatorConfigFromForm = (): Record<string, unknown> => {
    if (pluginId === "regex") {
      return { pattern: regexForm.values.pattern };
    } else if (pluginId === "list") {
      const values = listForm.values.values
        .split("\n")
        .filter((v) => v.trim() !== "");
      return {
        values,
        logic: listForm.values.logic,
        match_on: listForm.values.matchOn,
        match_mode: listForm.values.matchMode,
        case_sensitive: listForm.values.caseSensitive,
      };
    }
    return {};
  };

  // Helper to sync form values to JSON
  const syncFormToJson = () => {
    const config = getEvaluatorConfigFromForm();
    setRawJsonText(JSON.stringify(config, null, 2));
    setRawJsonError(null);
  };

  // Helper to sync JSON to form values
  const syncJsonToForm = (config: Record<string, unknown>) => {
    if (pluginId === "regex") {
      regexForm.setValues({
        pattern: (config.pattern as string) || "^.*$",
      });
    } else if (pluginId === "list") {
      const values = (config.values as string[]) || [];
      listForm.setValues({
        values: values.join("\n"),
        logic: (config.logic as ListFormValues["logic"]) || "any",
        matchOn: (config.match_on as ListFormValues["matchOn"]) || "match",
        matchMode:
          (config.match_mode as ListFormValues["matchMode"]) || "exact",
        caseSensitive: (config.case_sensitive as boolean) || false,
      });
    }
  };

  // Handle view mode changes
  const handleConfigViewModeChange = (value: string) => {
    if (value === "json" && configViewMode === "form") {
      // Switching from form to JSON - sync form values to JSON
      syncFormToJson();
    } else if (value === "form" && configViewMode === "json") {
      // Switching from JSON to form - parse and sync to form
      if (jsonViewMode === "raw" && rawJsonText) {
        try {
          const parsed = JSON.parse(rawJsonText);
          syncJsonToForm(parsed);
          setRawJsonError(null);
        } catch {
          setRawJsonError("Invalid JSON. Please fix before switching to form.");
          return;
        }
      }
    }
    setConfigViewMode(value as ConfigViewMode);
  };

  const handleJsonViewModeChange = (mode: JsonViewMode) => {
    if (mode === "raw" && jsonViewMode === "tree") {
      // Switching to raw - serialize current form config
      syncFormToJson();
    } else if (mode === "tree" && jsonViewMode === "raw") {
      // Switching to tree - parse raw JSON and sync to form
      try {
        const parsed = JSON.parse(rawJsonText);
        syncJsonToForm(parsed);
        setRawJsonError(null);
      } catch {
        setRawJsonError("Invalid JSON. Please fix before switching views.");
        return;
      }
    }
    setJsonViewMode(mode);
  };

  // Handle raw JSON text changes
  const handleRawJsonChange = (value: string) => {
    setRawJsonText(value);
    try {
      JSON.parse(value);
      setRawJsonError(null);
    } catch {
      setRawJsonError("Invalid JSON");
    }
  };

  // Update form fields when control changes
  useEffect(() => {
    if (control) {
      form.setValues({
        name: control.name,
        enabled: control.control.enabled,
        appliesTo: control.control.applies_to,
        checkStage: control.control.check_stage,
        selectorPath: control.control.selector.path ?? "*",
        actionDecision: control.control.action.decision,
        local: control.control.local,
      });

      // Set evaluator config based on plugin type
      const config = control.control.evaluator.config;
      const plugin = control.control.evaluator.plugin;

      if (plugin === "regex") {
        regexForm.setValues({
          pattern: (config.pattern as string) || "^.*$",
        });
      } else if (plugin === "list") {
        const values = (config.values as string[]) || [];
        listForm.setValues({
          values: values.join("\n"),
          logic: (config.logic as ListFormValues["logic"]) || "any",
          matchOn: (config.match_on as ListFormValues["matchOn"]) || "match",
          matchMode:
            (config.match_mode as ListFormValues["matchMode"]) || "exact",
          caseSensitive: (config.case_sensitive as boolean) || false,
        });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [control]);

  const handleSubmit = (values: ControlDefinitionFormValues) => {
    if (!control) return;

    // Get evaluator config based on view mode
    let finalConfig: Record<string, unknown>;
    if (configViewMode === "json") {
      if (jsonViewMode === "raw") {
        try {
          finalConfig = JSON.parse(rawJsonText);
        } catch {
          setRawJsonError("Invalid JSON. Please fix before saving.");
          return;
        }
      } else {
        // Tree view - parse from rawJsonText if available, otherwise from form
        try {
          finalConfig = rawJsonText
            ? JSON.parse(rawJsonText)
            : getEvaluatorConfigFromForm();
        } catch {
          finalConfig = getEvaluatorConfigFromForm();
        }
      }
    } else {
      // Form view - validate and get from the appropriate form
      let isValid = true;
      if (pluginId === "regex") {
        const validationResult = regexForm.validate();
        isValid = !validationResult.hasErrors;
      } else if (pluginId === "list") {
        const validationResult = listForm.validate();
        isValid = !validationResult.hasErrors;
      }

      if (!isValid) {
        return;
      }

      finalConfig = getEvaluatorConfigFromForm();
    }

    const updatedControl: Control = {
      ...control,
      name: values.name,
      control: {
        ...control.control,
        enabled: values.enabled,
        applies_to: values.appliesTo,
        check_stage: values.checkStage,
        selector: {
          ...control.control.selector,
          path: values.selectorPath,
        },
        action: { decision: values.actionDecision },
        local: values.local,
        evaluator: {
          ...control.control.evaluator,
          config: finalConfig,
        },
      },
    };
    onSave(updatedControl);
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title='Configure Control'
      size='xl'
      styles={{
        body: {
          maxHeight: "75vh",
          overflow: "auto",
        },
        title: {
          fontSize: "18px",
          fontWeight: 600,
        },
        content: {
          maxWidth: "1200px",
          width: "90vw",
        },
      }}
    >
      <form onSubmit={form.onSubmit(handleSubmit)}>
        {/* Control Name Field */}
        <TextInput
          label='Control name'
          placeholder='Enter control name'
          mb='lg'
          size='sm'
          {...form.getInputProps("name")}
        />

        <Grid gutter='xl'>
          {/* Left Column - Control Definition Fields */}
          <Grid.Col span={4}>
            <ControlDefinitionForm form={form} />
          </Grid.Col>

          {/* Right Column - Evaluator Config */}
          <Grid.Col span={8}>
            <Stack gap='md' h='100%'>
              {/* Header with view mode toggle */}
              <Group justify='space-between' align='center'>
                <Group gap='xs'>
                  <Text size='sm' fw={500}>
                    Evaluator configuration
                  </Text>
                  <Anchor
                    href='https://docs.galileo.ai/controls'
                    target='_blank'
                    size='xs'
                    c='blue'
                    underline='never'
                  >
                    <Group gap={2} align='center'>
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
                  size='xs'
                />
              </Group>

              {/* Form View */}
              {configViewMode === "form" && (
                <Paper withBorder radius='sm' p={16}>
                  <ScrollArea mah={500} mih={400} type='auto'>
                    <EvaluatorConfigForm
                      pluginId={pluginId}
                      regexForm={regexForm}
                      listForm={listForm}
                    />
                  </ScrollArea>
                </Paper>
              )}

              {/* JSON View */}
              {configViewMode === "json" && (
                <EvaluatorJsonView
                  config={getEvaluatorConfigFromForm()}
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

        <Divider mt='xl' mb='md' />

        <Group justify='flex-end'>
          <Button
            variant='outline'
            onClick={onClose}
            type='button'
            data-testid='cancel-button'
          >
            Cancel
          </Button>
          <Button variant='filled' type='submit' data-testid='save-button'>
            Save
          </Button>
        </Group>
      </form>
    </Modal>
  );
};
