import {
  Alert,
  Badge,
  Box,
  Divider,
  Grid,
  Group,
  Paper,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Button } from '@rungalileo/jupiter-ds';
import { useCallback, useMemo, useState } from 'react';

import { JsonEditorMonaco } from '@/components/json-editor-monaco';
import { api } from '@/core/api/client';
import { isApiError, parseApiError } from '@/core/api/errors';
import type {
  Control,
  ProblemDetail,
  TemplateControlInput,
  TemplateValue,
} from '@/core/api/types';
import { TemplateParamForm } from '@/core/components/template-param-form';
import { TemplatePreview } from '@/core/components/template-preview';
import { useAgent } from '@/core/hooks/query-hooks/use-agent';
import { useControlSchema } from '@/core/hooks/query-hooks/use-control-schema';
import { useEvaluators } from '@/core/hooks/query-hooks/use-evaluators';
import { useUpdateControl } from '@/core/hooks/query-hooks/use-update-control';
import { useUpdateControlMetadata } from '@/core/hooks/query-hooks/use-update-control-metadata';
import { openActionConfirmModal } from '@/core/utils/modals';

import { ApiErrorAlert } from './api-error-alert';
import type { JsonEditorEvaluatorOption } from './types';

type TemplateEditContentProps = {
  control: Control;
  agentId: string;
  onClose: () => void;
  onSuccess?: () => void;
};

type EditorMode = 'params' | 'json';

/**
 * Editor for template-backed controls. Shows the parameter form by default,
 * with a toggle to edit the full template JSON.
 */
export function TemplateEditContent({
  control,
  agentId,
  onClose,
  onSuccess,
}: TemplateEditContentProps) {
  // Access template fields via cast — these exist at runtime but aren't in the
  // generated API types yet. Will be cleaned up after type regeneration.
  const definitionRaw = control.control as Record<string, unknown>;
  const template = definitionRaw.template as TemplateControlInput['template'];
  const storedValues = definitionRaw.template_values as
    | Record<string, TemplateValue>
    | undefined;

  const [editorMode, setEditorMode] = useState<EditorMode>('params');
  const [controlName, setControlName] = useState(control.name);
  const [templateValues, setTemplateValues] = useState<
    Record<string, TemplateValue>
  >(storedValues ?? {});
  const [paramErrors, setParamErrors] = useState<Record<string, string>>({});
  const [apiError, setApiError] = useState<ProblemDetail | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);

  // JSON editor state
  const [jsonText, setJsonText] = useState('');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [templateValidationError, setTemplateValidationError] =
    useState<ProblemDetail | null>(null);

  const updateControl = useUpdateControl();
  const updateControlMetadata = useUpdateControlMetadata();
  const isPending = updateControl.isPending || updateControlMetadata.isPending;

  // Hooks for smart JSON editor features
  const { data: controlSchemaResponse } = useControlSchema();
  const { data: globalEvaluators } = useEvaluators();
  const { data: agentResponse } = useAgent(agentId);
  const steps = agentResponse?.steps ?? [];
  const agentName = agentResponse?.agent?.agent_name ?? agentId;

  const availableEvaluators = useMemo<JsonEditorEvaluatorOption[]>(() => {
    const merged = new Map<string, JsonEditorEvaluatorOption>();
    for (const [id, evaluatorInfo] of Object.entries(globalEvaluators ?? {})) {
      merged.set(id, {
        id,
        label: evaluatorInfo.name,
        description: evaluatorInfo.description,
        source: 'global',
        configSchema: evaluatorInfo.config_schema,
      });
    }
    for (const evaluatorSchema of agentResponse?.evaluators ?? []) {
      const id = `${agentName}:${evaluatorSchema.name}`;
      merged.set(id, {
        id,
        label: evaluatorSchema.name,
        description: evaluatorSchema.description,
        source: 'agent',
        configSchema: evaluatorSchema.config_schema,
      });
    }
    return [...merged.values()];
  }, [agentName, agentResponse?.evaluators, globalEvaluators]);

  // Dynamically extract parameter names from the current JSON text so
  // completions update as the user edits the parameters block.
  const templateParameterNames = useMemo(() => {
    if (editorMode !== 'json') return Object.keys(template.parameters);
    try {
      const parsed = JSON.parse(jsonText) as TemplateControlInput;
      return Object.keys(parsed?.template?.parameters ?? {});
    } catch {
      return Object.keys(template.parameters);
    }
  }, [editorMode, jsonText, template.parameters]);

  const validateTemplateJson = useCallback(
    async (parsed: Record<string, unknown>) => {
      const input = parsed as TemplateControlInput;
      if (!input.template?.definition_template) return;

      const { error, response } = await api.controlTemplates.render({
        template: input.template,
        template_values: input.template_values ?? {},
      });
      if (error) {
        throw parseApiError(
          error,
          'Template validation failed',
          response?.status
        );
      }
    },
    []
  );

  const handlePreviewErrors = useCallback((errors: Record<string, string>) => {
    setParamErrors(errors);
  }, []);

  const buildTemplateInput = useCallback((): TemplateControlInput => {
    return {
      template: template as TemplateControlInput['template'],
      template_values: templateValues,
    };
  }, [template, templateValues]);

  const handleEditorModeChange = (value: string) => {
    const next = value as EditorMode;
    if (next === editorMode) return;

    if (next === 'json') {
      // Params → JSON: serialize current state
      const input = buildTemplateInput();
      setJsonText(JSON.stringify(input, null, 2));
      setJsonError(null);
      setEditorMode('json');
      return;
    }

    // JSON → Params: parse and sync back
    try {
      const parsed = JSON.parse(jsonText) as TemplateControlInput;
      if (!parsed.template?.definition_template) {
        setJsonError(
          'JSON must contain a "template" object with "definition_template".'
        );
        return;
      }
      setTemplateValues(parsed.template_values ?? {});
      setJsonError(null);
      setEditorMode('params');
    } catch {
      setJsonError(
        'Invalid JSON. Fix syntax errors before switching to Parameters.'
      );
    }
  };

  const handleSave = () => {
    if (!controlName.trim()) {
      setNameError('Control name is required');
      return;
    }
    setNameError(null);

    let templateInput: TemplateControlInput;

    if (editorMode === 'json') {
      try {
        templateInput = JSON.parse(jsonText) as TemplateControlInput;
        if (!templateInput.template?.definition_template) {
          setJsonError(
            'JSON must contain a "template" object with "definition_template".'
          );
          return;
        }
      } catch {
        setJsonError('Invalid JSON. Fix syntax errors before saving.');
        return;
      }
    } else {
      templateInput = buildTemplateInput();
    }

    openActionConfirmModal({
      title: 'Save changes?',
      children: (
        <Text size="sm" c="dimmed">
          This will update the control configuration.
        </Text>
      ),
      onConfirm: async () => {
        setApiError(null);
        try {
          // Update name if changed
          const nameChanged = controlName.trim() !== control.name.trim();
          if (nameChanged) {
            try {
              await updateControlMetadata.mutateAsync({
                agentId,
                controlId: control.id,
                data: { name: controlName.trim() },
              });
            } catch (renameError) {
              if (isApiError(renameError)) {
                const pd = renameError.problemDetail;
                if (
                  pd.status === 409 ||
                  pd.error_code === 'CONTROL_NAME_CONFLICT'
                ) {
                  setNameError(pd.detail || 'Control name already exists');
                } else {
                  setApiError(pd);
                }
              } else {
                notifications.show({
                  title: 'Failed to rename control',
                  message:
                    renameError instanceof Error
                      ? renameError.message
                      : 'An unexpected error occurred',
                  color: 'red',
                });
              }
              return;
            }
          }

          // Update template values
          await updateControl.mutateAsync({
            agentId,
            controlId: control.id,
            definition: templateInput as never,
          });

          notifications.show({
            title: 'Control updated',
            message: `"${controlName.trim()}" has been saved.`,
            color: 'green',
          });

          if (onSuccess) {
            onSuccess();
          } else {
            onClose();
          }
        } catch (error) {
          if (isApiError(error)) {
            const pd = error.problemDetail;
            setApiError(pd);
            if (pd.errors) {
              const newParamErrors: Record<string, string> = {};
              for (const item of pd.errors) {
                if (item.field?.startsWith('template_values.')) {
                  const paramName = item.field.replace('template_values.', '');
                  newParamErrors[paramName] = item.message;
                }
              }
              if (Object.keys(newParamErrors).length > 0) {
                setParamErrors(newParamErrors);
              }
            }
          } else {
            notifications.show({
              title: 'Failed to update control',
              message:
                error instanceof Error
                  ? error.message
                  : 'An unexpected error occurred',
              color: 'red',
            });
          }
        }
      },
    });
  };

  // Extract read-only summary from the rendered control
  const action =
    (definitionRaw.action as { decision?: string })?.decision ?? 'unknown';
  const execution = (definitionRaw.execution as string) ?? 'server';
  const description = definitionRaw.description as string | undefined;

  return (
    <Box>
      <Stack gap="md" mb="lg">
        <Group justify="space-between" align="flex-end" wrap="nowrap">
          <Box style={{ flex: 1, maxWidth: 420 }}>
            <TextInput
              label="Control name"
              placeholder="Enter control name"
              size="sm"
              required
              value={controlName}
              onChange={(e) => {
                setControlName(e.currentTarget.value);
                setNameError(null);
              }}
              error={nameError}
            />
          </Box>
          <Group gap="xs">
            <Badge variant="light" color="blue" size="lg">
              Template
            </Badge>
            <SegmentedControl
              value={editorMode}
              onChange={handleEditorModeChange}
              data={[
                { value: 'params', label: 'Parameters' },
                { value: 'json', label: 'Full JSON' },
              ]}
              size="xs"
            />
          </Group>
        </Group>
      </Stack>

      {editorMode === 'json' ? (
        <Paper withBorder radius="sm" p={16}>
          <JsonEditorMonaco
            jsonText={jsonText}
            handleJsonChange={(text) => {
              setJsonText(text);
              setJsonError(null);
            }}
            jsonError={jsonError}
            setJsonError={setJsonError}
            validationError={templateValidationError}
            setValidationError={setTemplateValidationError}
            onValidateConfig={validateTemplateJson}
            height={520}
            label="Template definition (JSON)"
            tooltip="Edit the full template input JSON. Control name stays separate."
            helperText="Edit template parameters, definition_template, and template_values."
            testId="template-json-textarea"
            editorMode="template"
            schema={controlSchemaResponse?.schema ?? null}
            evaluators={availableEvaluators}
            steps={steps}
            templateParameterNames={templateParameterNames}
          />
        </Paper>
      ) : (
        <Grid gutter="xl">
          {/* Left panel: read-only summary */}
          <Grid.Col span={4}>
            <Stack gap="md">
              {description ? (
                <Box>
                  <Text size="xs" fw={500} c="dimmed" mb={2}>
                    Description
                  </Text>
                  <Text size="sm">{description}</Text>
                </Box>
              ) : null}
              <Box>
                <Text size="xs" fw={500} c="dimmed" mb={2}>
                  Action
                </Text>
                <Badge variant="light" size="sm">
                  {action}
                </Badge>
              </Box>
              <Box>
                <Text size="xs" fw={500} c="dimmed" mb={2}>
                  Execution
                </Text>
                <Text size="sm">{execution}</Text>
              </Box>
              {template.description ? (
                <Paper withBorder p="sm" radius="sm">
                  <Text size="xs" c="dimmed" fw={500} mb={4}>
                    Template
                  </Text>
                  <Text size="xs">{template.description}</Text>
                </Paper>
              ) : null}
              <Alert variant="light" color="blue" p="xs">
                <Text size="xs">
                  Scope, condition, and action are managed by the template. Edit
                  the parameters on the right to change control behavior.
                </Text>
              </Alert>
            </Stack>
          </Grid.Col>

          {/* Right panel: parameter form + preview */}
          <Grid.Col span={8}>
            <Stack gap="md">
              <Text size="sm" fw={500}>
                Template Parameters
              </Text>
              <TemplateParamForm
                template={template as TemplateControlInput['template']}
                values={templateValues}
                onChange={setTemplateValues}
                errors={paramErrors}
              />

              <Divider />

              <TemplatePreview
                template={template as TemplateControlInput['template']}
                values={templateValues}
                onErrors={handlePreviewErrors}
              />
            </Stack>
          </Grid.Col>
        </Grid>
      )}

      {apiError ? (
        <>
          <Divider mt="xl" mb="md" />
          <ApiErrorAlert
            error={apiError}
            unmappedErrors={[]}
            onClose={() => setApiError(null)}
          />
        </>
      ) : null}

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
          onClick={handleSave}
          data-testid="save-button"
          loading={isPending}
        >
          Save
        </Button>
      </Group>
    </Box>
  );
}
