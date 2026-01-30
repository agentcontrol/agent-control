import { Group, Modal, Stack, Textarea, TextInput } from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import { Button } from "@rungalileo/jupiter-ds";
import { IconCheck } from "@tabler/icons-react";

import { useCreateEvaluatorConfig } from "@/core/hooks/query-hooks/use-create-evaluator-config";

import type { ConfigViewMode } from "../edit-control/types";

interface SaveEvaluatorTemplateModalProps {
  opened: boolean;
  onClose: () => void;
  evaluatorId: string;
  configViewMode: ConfigViewMode;
  rawJsonText: string;
  getEvaluatorConfig: () => Record<string, unknown>;
  validateEvaluatorForm: () => boolean;
}

export const SaveEvaluatorTemplateModal = ({
  opened,
  onClose,
  evaluatorId,
  configViewMode,
  rawJsonText,
  getEvaluatorConfig,
  validateEvaluatorForm,
}: SaveEvaluatorTemplateModalProps) => {
  const createEvaluatorConfig = useCreateEvaluatorConfig();
  const templateForm = useForm({
    initialValues: {
      name: "",
      description: "",
    },
    validate: {
      name: (value) => {
        if (!value.trim()) return "Template name is required";
        if (!/^[a-zA-Z0-9_-]+$/.test(value)) {
          return "Name can only contain letters, numbers, hyphens, and underscores";
        }
        return null;
      },
    },
  });

  const handleClose = () => {
    onClose();
    templateForm.reset();
  };

  const handleSaveAsTemplate = async (values: { name: string; description: string }) => {
    let finalConfig: Record<string, unknown>;

    if (configViewMode === "json") {
      try {
        finalConfig = JSON.parse(rawJsonText || "{}");
      } catch {
        notifications.show({
          title: "Invalid JSON",
          message: "Please fix the JSON before saving as template.",
          color: "red",
        });
        return;
      }
    } else {
      const isValid = validateEvaluatorForm();
      if (!isValid) {
        notifications.show({
          title: "Validation Error",
          message: "Please fix form errors before saving as template.",
          color: "red",
        });
        return;
      }
      finalConfig = getEvaluatorConfig();
    }

    try {
      await createEvaluatorConfig.mutateAsync({
        name: values.name,
        description: values.description || undefined,
        evaluator: evaluatorId,
        config: finalConfig,
      });

      notifications.show({
        title: "Template Saved",
        message: `"${values.name}" has been saved as a reusable template.`,
        color: "green",
        icon: <IconCheck size={16} />,
      });

      handleClose();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to save template";
      notifications.show({
        title: "Error",
        message,
        color: "red",
      });
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      title="Save Evaluator Config as Template"
      size="sm"
    >
      <form
        onSubmit={(event) => {
          event.stopPropagation();
          templateForm.onSubmit(handleSaveAsTemplate)(event);
        }}
      >
        <Stack gap="md">
          <TextInput
            label="Template Name"
            placeholder="e.g., pii-detection-strict"
            description="Letters, numbers, hyphens, and underscores only"
            required
            data-testid="template-name-input"
            {...templateForm.getInputProps("name")}
          />
          <Textarea
            label="Description"
            placeholder="Optional description for this template"
            rows={3}
            data-testid="template-description-input"
            {...templateForm.getInputProps("description")}
          />
          <Group justify="flex-end" mt="md">
            <Button
              variant="outline"
              onClick={handleClose}
              data-testid="cancel-template-button"
            >
              Cancel
            </Button>
            <Button
              variant="filled"
              type="submit"
              loading={createEvaluatorConfig.isPending}
              data-testid="save-template-button"
            >
              Save Template
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
};
