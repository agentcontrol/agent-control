import {
  Alert,
  Box,
  Divider,
  Grid,
  Group,
  Paper,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { Button } from '@rungalileo/jupiter-ds';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { JsonEditorMonaco } from '@/components/json-editor-monaco';
import { isApiError } from '@/core/api/errors';
import type {
  Control,
  ControlDefinition,
  ProblemDetail,
} from '@/core/api/types';
import { useAddControlToAgent } from '@/core/hooks/query-hooks/use-add-control-to-agent';
import { useAgent } from '@/core/hooks/query-hooks/use-agent';
import { useControlSchema } from '@/core/hooks/query-hooks/use-control-schema';
import { useEvaluators } from '@/core/hooks/query-hooks/use-evaluators';
import { useUpdateControl } from '@/core/hooks/query-hooks/use-update-control';
import { useUpdateControlMetadata } from '@/core/hooks/query-hooks/use-update-control-metadata';
import { useValidateControlData } from '@/core/hooks/query-hooks/use-validate-control-data';
import {
  openActionConfirmModal,
  openDestructiveConfirmModal,
} from '@/core/utils/modals';

import { ApiErrorAlert } from './api-error-alert';
import {
  buildEditableCondition,
  getControlConditionState,
} from './control-condition';
import { ControlDefinitionForm } from './control-definition-form';
import { EvaluatorConfigSection } from './evaluator-config-section';
import type {
  ControlDefinitionFormValues,
  ControlEditorMode,
  EditControlMode,
  JsonEditorEvaluatorOption,
} from './types';
import { useEvaluatorConfigState } from './use-evaluator-config-state';
import { applyApiErrorsToForms } from './utils';

const EVALUATOR_CONFIG_HEIGHT = 450;
const JSON_EDITOR_HEIGHT = 520;
type ValidationStatus = 'idle' | 'validating' | 'valid' | 'invalid';

const DEFAULT_CONTROL_TEMPLATE = JSON.stringify(
  {
    description: 'Block outputs containing US Social Security Numbers',
    enabled: true,
    execution: 'server',
    scope: {
      step_types: ['llm'],
      stages: ['post'],
    },
    condition: {
      selector: { path: 'output' },
      evaluator: {
        name: 'regex',
        config: { pattern: '\\b\\d{3}-\\d{2}-\\d{4}\\b' },
      },
    },
    action: { decision: 'deny' },
    tags: ['pii', 'compliance'],
  },
  null,
  2
);

export type EditControlContentProps = {
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
  /** Initial editor mode */
  initialEditorMode?: ControlEditorMode;
  /**
   * Mutable ref that receives the close handler (with unsaved-changes check).
   * The parent Modal can use this ref for its own onClose so the X button
   * also triggers the dirty check.
   */
  onCloseRef?: React.MutableRefObject<(() => void) | null>;
};

export const EditControlContent = ({
  control,
  agentId,
  mode = 'edit',
  onClose,
  onSuccess,
  initialEditorMode = 'form',
  onCloseRef,
}: EditControlContentProps) => {
  const { data: agentResponse } = useAgent(agentId);
  const { data: controlSchemaResponse } = useControlSchema();
  const { data: globalEvaluators } = useEvaluators();
  const steps = agentResponse?.steps ?? [];
  const agentName = agentResponse?.agent?.agent_name ?? agentId;

  const [workingDefinition, setWorkingDefinition] = useState<ControlDefinition>(
    control.control
  );
  const [editorMode, setEditorMode] =
    useState<ControlEditorMode>(initialEditorMode);
  const [apiError, setApiError] = useState<ProblemDetail | null>(null);
  const [unmappedErrors, setUnmappedErrors] = useState<
    Array<{ field: string | null; message: string }>
  >([]);
  const [definitionJsonText, setDefinitionJsonText] = useState('');
  const [definitionJsonError, setDefinitionJsonError] = useState<string | null>(
    null
  );
  const [definitionValidationError, setDefinitionValidationError] =
    useState<ProblemDetail | null>(null);
  const [definitionValidationStatus, setDefinitionValidationStatus] =
    useState<ValidationStatus>('idle');
  const [isDirty, setIsDirty] = useState(false);

  const updateControl = useUpdateControl();
  const updateControlMetadata = useUpdateControlMetadata();
  const addControlToAgent = useAddControlToAgent();
  const { mutateAsync: validateControlDataAsync } = useValidateControlData();
  const isCreating = mode === 'create';
  const isPending = isCreating
    ? addControlToAgent.isPending
    : updateControl.isPending || updateControlMetadata.isPending;

  const formRef = useRef<HTMLFormElement>(null);
  const formInitializedForEvaluator = useRef<string>('');
  const { leafCondition, evaluatorId, evaluator, canEditLeafCondition } =
    useMemo(
      () => getControlConditionState(workingDefinition),
      [workingDefinition]
    );
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
  const activeEvaluatorOption = useMemo(
    () =>
      availableEvaluators.find((candidate) => candidate.id === evaluatorId) ??
      null,
    [availableEvaluators, evaluatorId]
  );

  const definitionForm = useForm<ControlDefinitionFormValues>({
    initialValues: {
      name: '',
      description: '',
      enabled: true,
      step_types: ['llm'],
      stages: ['post'],
      step_names: '',
      step_name_regex: '',
      step_name_mode: 'names',
      selector_path: '*',
      action_decision: 'deny',
      action_steering_context: '',
      execution: 'server',
    },
    validate: {
      name: (value) => (!value?.trim() ? 'Control name is required' : null),
      selector_path: (value) => {
        if (editorMode === 'json' || !canEditLeafCondition) {
          return null;
        }
        if (!value?.trim()) {
          return 'Selector path is required';
        }
        const validRoots = ['input', 'output', 'name', 'type', 'context', '*'];
        const root = value.split('.')[0];
        if (!validRoots.includes(root)) {
          return `Invalid path root '${root}'. Must be one of: ${validRoots.join(', ')}`;
        }
        return null;
      },
    },
  });

  const evaluatorForm = useForm({
    initialValues: evaluator?.initialValues ?? {},
    validate: evaluator?.validate,
  });

  const getEvaluatorConfig = useCallback(() => {
    if (!leafCondition) {
      return {};
    }
    if (!evaluator) {
      return leafCondition.evaluatorConfig;
    }
    if (formInitializedForEvaluator.current !== evaluatorId) {
      return evaluator.toConfig(evaluator.initialValues);
    }
    return evaluator.toConfig(evaluatorForm.values);
  }, [evaluator, evaluatorForm.values, evaluatorId, leafCondition]);

  const syncJsonToForm = useCallback(
    (config: Record<string, unknown>) => {
      if (evaluator) {
        evaluatorForm.setValues(evaluator.fromConfig(config));
      }
    },
    [evaluator, evaluatorForm]
  );

  const buildLeafCondition = useCallback(
    (
      values: ControlDefinitionFormValues,
      finalConfig: Record<string, unknown>
    ): ControlDefinition['condition'] => {
      return buildEditableCondition(
        workingDefinition,
        leafCondition,
        values.selector_path.trim(),
        finalConfig
      );
    },
    [leafCondition, workingDefinition]
  );

  const buildControlDefinition = useCallback(
    (
      values: ControlDefinitionFormValues,
      condition: ControlDefinition['condition']
    ): ControlDefinition => {
      const stepTypes = values.step_types
        .map((value) => value.trim())
        .filter(Boolean);
      const stepNames = values.step_names
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean);
      const stepNameRegex = values.step_name_regex.trim();
      const isRegexMode = values.step_name_mode === 'regex';

      const scope: Record<string, unknown> = {};
      if (stepTypes.length > 0) scope.step_types = stepTypes;
      if (!isRegexMode && stepNames.length > 0) scope.step_names = stepNames;
      if (isRegexMode && stepNameRegex) scope.step_name_regex = stepNameRegex;
      if (values.stages.length > 0) scope.stages = values.stages;

      return {
        description: values.description?.trim() || undefined,
        enabled: values.enabled,
        execution: values.execution,
        scope: Object.keys(scope).length > 0 ? scope : undefined,
        condition,
        action: {
          decision: values.action_decision,
          ...(values.action_decision === 'steer' &&
          values.action_steering_context?.trim()
            ? {
                steering_context: {
                  message: values.action_steering_context.trim(),
                },
              }
            : {}),
        },
        tags: workingDefinition.tags,
      };
    },
    [workingDefinition.tags]
  );

  const validateEvaluatorConfig = useCallback(
    async (
      config: Record<string, unknown>,
      options?: { signal?: AbortSignal }
    ) => {
      const condition = buildLeafCondition(definitionForm.values, config);
      await validateControlDataAsync({
        definition: buildControlDefinition(definitionForm.values, condition),
        signal: options?.signal,
      });
    },
    [
      buildControlDefinition,
      buildLeafCondition,
      definitionForm.values,
      validateControlDataAsync,
    ]
  );

  const evaluatorConfig = useEvaluatorConfigState({
    getConfigFromForm: getEvaluatorConfig,
    onConfigChange: syncJsonToForm,
    onValidateConfig: validateEvaluatorConfig,
  });

  const { reset } = evaluatorConfig;

  const getDefinitionFromFormState =
    useCallback((): ControlDefinition | null => {
      let condition: ControlDefinition['condition'];

      if (canEditLeafCondition) {
        let finalConfig: Record<string, unknown> =
          leafCondition?.evaluatorConfig ?? {};

        if (evaluatorConfig.configViewMode === 'json') {
          const jsonConfig = evaluatorConfig.getJsonConfig();
          if (!jsonConfig) return null;
          finalConfig = jsonConfig;
        } else {
          finalConfig = getEvaluatorConfig();
        }

        condition = buildLeafCondition(definitionForm.values, finalConfig);
      } else {
        condition = workingDefinition.condition;
      }

      return buildControlDefinition(definitionForm.values, condition);
    }, [
      buildControlDefinition,
      buildLeafCondition,
      canEditLeafCondition,
      definitionForm.values,
      evaluatorConfig,
      getEvaluatorConfig,
      leafCondition?.evaluatorConfig,
      workingDefinition.condition,
    ]);

  const handleDefinitionJsonChange = useCallback((value: string) => {
    setDefinitionJsonText(value);
    setDefinitionJsonError(null);
    setDefinitionValidationError(null);
    setIsDirty(true);
  }, []);

  const getJsonDefinition = useCallback((): ControlDefinition | null => {
    if (!definitionJsonText.trim()) {
      setDefinitionJsonError(
        'Control JSON is required. Please add a control definition.'
      );
      setDefinitionValidationError(null);
      return null;
    }

    try {
      setDefinitionJsonError(null);
      return JSON.parse(definitionJsonText) as ControlDefinition;
    } catch {
      setDefinitionJsonError('Invalid JSON. Please fix before saving.');
      setDefinitionValidationError(null);
      return null;
    }
  }, [definitionJsonText]);

  const validateDefinitionJson = useCallback(
    async (
      definition: Record<string, unknown>,
      options?: { signal?: AbortSignal }
    ) => {
      await validateControlDataAsync({
        definition: definition as ControlDefinition,
        signal: options?.signal,
      });
    },
    [validateControlDataAsync]
  );

  const handleEditorModeChange = useCallback(
    async (value: string) => {
      const nextMode = value as ControlEditorMode;

      if (nextMode === editorMode) {
        return;
      }

      if (nextMode === 'json') {
        const definition = getDefinitionFromFormState();
        if (!definition) {
          return;
        }

        setDefinitionJsonText(JSON.stringify(definition, null, 2));
        setDefinitionJsonError(null);
        setDefinitionValidationError(null);
        setDefinitionValidationStatus('idle');
        setEditorMode('json');
        return;
      }

      const parsedDefinition = getJsonDefinition();
      if (!parsedDefinition) {
        return;
      }

      try {
        await validateControlDataAsync({ definition: parsedDefinition });
      } catch (error) {
        if (isApiError(error)) {
          setDefinitionValidationError(error.problemDetail);
          setDefinitionJsonError(null);
          setDefinitionValidationStatus('invalid');
        } else {
          setDefinitionJsonError('Validation failed.');
          setDefinitionValidationError(null);
          setDefinitionValidationStatus('invalid');
        }
        return;
      }

      setWorkingDefinition(parsedDefinition);
      setDefinitionJsonError(null);
      setDefinitionValidationError(null);
      setDefinitionValidationStatus('idle');
      setEditorMode('form');
    },
    [
      editorMode,
      getDefinitionFromFormState,
      getJsonDefinition,
      validateControlDataAsync,
    ]
  );

  useEffect(() => {
    if (definitionForm.values.action_decision !== 'steer') {
      definitionForm.setFieldValue('action_steering_context', '');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [definitionForm.values.action_decision]);

  useEffect(() => {
    setWorkingDefinition(control.control);
    setEditorMode(initialEditorMode);
    setDefinitionJsonText(
      initialEditorMode === 'json'
        ? mode === 'create'
          ? DEFAULT_CONTROL_TEMPLATE
          : JSON.stringify(control.control, null, 2)
        : ''
    );
    setDefinitionJsonError(null);
    setDefinitionValidationError(null);
    setDefinitionValidationStatus('idle');
    setIsDirty(false);
  }, [control.control, initialEditorMode]);

  useEffect(() => {
    reset();
    setApiError(null);
    setUnmappedErrors([]);
    formInitializedForEvaluator.current = '';
  }, [reset, evaluatorId, control.id, workingDefinition]);

  useEffect(() => {
    const scope = workingDefinition.scope ?? {};
    const stepNamesValue = (scope.step_names ?? []).join(', ');
    const stepRegexValue = scope.step_name_regex ?? '';
    const stepNameMode: 'regex' | 'names' =
      stepRegexValue && !stepNamesValue ? 'regex' : 'names';

    // Preserve the user-edited control name. The name lives outside the JSON
    // definition, so syncing workingDefinition→form should not overwrite it.
    // control.name is only used as the initial value (set in the earlier
    // control.control reset effect).
    const currentName = definitionForm.values.name;

    const syncedValues = {
      name: currentName || control.name,
      description: workingDefinition.description ?? '',
      enabled: workingDefinition.enabled,
      step_types: scope.step_types ?? [],
      stages: scope.stages ?? [],
      step_names: stepNamesValue,
      step_name_regex: stepRegexValue,
      step_name_mode: stepNameMode,
      selector_path: leafCondition?.selectorPath ?? '*',
      action_decision: workingDefinition.action.decision,
      action_steering_context:
        workingDefinition.action.decision === 'steer'
          ? (workingDefinition.action.steering_context?.message ?? '')
          : '',
      execution: workingDefinition.execution ?? 'server',
    };
    definitionForm.setValues(syncedValues);
    definitionForm.resetDirty(syncedValues);

    if (leafCondition && evaluator) {
      evaluatorForm.setValues(
        evaluator.fromConfig(leafCondition.evaluatorConfig)
      );
      formInitializedForEvaluator.current = evaluatorId;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [control.name, evaluator, evaluatorId, leafCondition, workingDefinition]);

  const handleSubmit = async (values: ControlDefinitionFormValues) => {
    setApiError(null);
    setUnmappedErrors([]);
    definitionForm.clearErrors();
    evaluatorForm.clearErrors();

    // Bug fix #1: Explicitly validate the name before opening the confirm
    // dialog. The HTML5 `required` attribute may silently block submission
    // without showing a visible Mantine error message.
    const nameValidation = definitionForm.validateField('name');
    if (nameValidation.hasError) {
      return;
    }

    if (
      editorMode === 'form' &&
      values.action_decision === 'steer' &&
      !leafCondition &&
      !values.action_steering_context?.trim()
    ) {
      definitionForm.setFieldError(
        'action_steering_context',
        'Composite steer controls require steering context'
      );
      return;
    }

    let definition: ControlDefinition | null = null;

    if (editorMode === 'json') {
      definition = getJsonDefinition();
      if (!definition) {
        return;
      }
    } else {
      if (canEditLeafCondition && evaluatorConfig.configViewMode === 'form') {
        const validation = evaluatorForm.validate();
        if (validation.hasErrors) return;
      }

      definition = getDefinitionFromFormState();
      if (!definition) {
        return;
      }
    }

    const runSave = async () => {
      try {
        if (!definition) {
          return;
        }
        await validateControlDataAsync({ definition });

        if (isCreating) {
          await addControlToAgent.mutateAsync({
            agentId,
            controlName: values.name,
            definition,
          });
          notifications.show({
            title: 'Control created',
            message: `"${values.name.trim()}" has been added to this agent.`,
            color: 'green',
          });
        } else {
          const nameChanged = values.name.trim() !== control.name.trim();

          if (nameChanged) {
            try {
              await updateControlMetadata.mutateAsync({
                agentId,
                controlId: control.id,
                data: { name: values.name },
              });
            } catch (renameError) {
              if (isApiError(renameError)) {
                const problemDetail = renameError.problemDetail;

                if (
                  problemDetail.status === 409 ||
                  problemDetail.error_code === 'CONTROL_NAME_CONFLICT'
                ) {
                  definitionForm.setFieldError(
                    'name',
                    problemDetail.detail || 'Control name already exists'
                  );
                } else if (problemDetail.status === 422) {
                  setApiError(problemDetail);
                  if (problemDetail.errors) {
                    const unmapped = applyApiErrorsToForms(
                      problemDetail.errors,
                      definitionForm,
                      canEditLeafCondition ? evaluatorForm : null
                    );
                    setUnmappedErrors(
                      unmapped.map((e) => ({
                        field: e.field,
                        message: e.message,
                      }))
                    );
                  }
                } else {
                  notifications.show({
                    title: 'Failed to rename control',
                    message:
                      problemDetail.detail ||
                      'An unexpected error occurred while renaming',
                    color: 'red',
                  });
                }
              } else {
                notifications.show({
                  title: 'Failed to rename control',
                  message:
                    renameError instanceof Error
                      ? renameError.message
                      : 'An unexpected error occurred while renaming',
                  color: 'red',
                });
              }
              return;
            }
          }

          await updateControl.mutateAsync({
            agentId,
            controlId: control.id,
            definition,
          });
          notifications.show({
            title: 'Control updated',
            message: `"${values.name.trim()}" has been saved.`,
            color: 'green',
          });
        }

        if (onSuccess) {
          onSuccess();
        } else {
          onClose();
        }
      } catch (error) {
        if (isApiError(error)) {
          const problemDetail = error.problemDetail;
          const isNameExistsError =
            (problemDetail.status === 409 ||
              problemDetail.error_code === 'CONTROL_NAME_CONFLICT') &&
            !problemDetail.errors?.some((item) => item.field === 'name');

          if (isNameExistsError) {
            definitionForm.setFieldError(
              'name',
              problemDetail.detail || 'Control name already exists'
            );
            setApiError(null);
            setUnmappedErrors([]);
            return;
          }

          setApiError(problemDetail);

          if (problemDetail.errors) {
            if (editorMode === 'json') {
              setUnmappedErrors(
                problemDetail.errors.map((e) => ({
                  field: e.field,
                  message: e.message,
                }))
              );
            } else if (evaluatorConfig.configViewMode === 'form') {
              const unmapped = applyApiErrorsToForms(
                problemDetail.errors,
                definitionForm,
                canEditLeafCondition ? evaluatorForm : null
              );
              setUnmappedErrors(
                unmapped.map((e) => ({
                  field: e.field,
                  message: e.message,
                }))
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
        } else {
          setApiError({
            type: 'about:blank',
            title: 'Error',
            status: 500,
            detail:
              error instanceof Error
                ? error.message
                : 'An unexpected error occurred',
            error_code: 'UNKNOWN_ERROR',
            reason: 'Unknown',
          });
        }
      }
    };

    const modalId = openActionConfirmModal({
      title: isCreating ? 'Create control?' : 'Save changes?',
      children: (
        <Text size="sm" c="dimmed">
          {isCreating
            ? 'This will add the new control to the agent.'
            : 'This will update the control configuration.'}
        </Text>
      ),
      onConfirm: () => {
        // Close the confirm modal immediately so a second click cannot
        // fire another request (the Save button's `loading` state handles
        // the rest of the pending UX).
        modals.close(modalId);
        runSave();
      },
    });
  };

  // --- Cmd+S / Ctrl+S shortcut to trigger Save ---
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        formRef.current?.requestSubmit();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  const handleClose = useCallback(() => {
    if (!isCreating && isDirty) {
      openDestructiveConfirmModal({
        title: 'Discard unsaved changes?',
        children: (
          <Text size="sm" c="dimmed">
            You have unsaved changes. Are you sure you want to close?
          </Text>
        ),
        confirmLabel: 'Discard',
        onConfirm: () => {
          if (onCloseRef) onCloseRef.current = null;
          onClose();
        },
      });
      return;
    }
    // Clear the ref so the parent's onClose won't re-enter handleClose.
    if (onCloseRef) onCloseRef.current = null;
    onClose();
  }, [isDirty, onClose, isCreating, onCloseRef]);

  // Expose handleClose to the parent so the Modal X button also checks dirty state.
  useEffect(() => {
    if (onCloseRef) onCloseRef.current = handleClose;
    return () => {
      if (onCloseRef) onCloseRef.current = null;
    };
  }, [handleClose, onCloseRef]);

  const formComponent = evaluator?.FormComponent;
  const definitionStatusLabel = (() => {
    if (editorMode !== 'json') return null;
    if (definitionValidationStatus === 'validating')
      return 'JSON validating...';
    if (definitionValidationStatus === 'valid') return 'JSON valid';
    if (definitionValidationStatus === 'invalid') return 'JSON invalid';
    return null;
  })();
  const definitionStatusColor =
    definitionValidationStatus === 'valid'
      ? 'green'
      : definitionValidationStatus === 'invalid'
        ? 'red'
        : 'dimmed';
  // Only disable the mode toggle for JSON *parse* errors (broken syntax the
  // user must fix in JSON mode). Server-side validation errors (missing fields,
  // bad values) should NOT lock the toggle — the user may want to switch to
  // Form mode to fix them more easily.
  const isDefinitionJsonParseError =
    editorMode === 'json' && definitionJsonError !== null;

  return (
    <Box>
      <form
        ref={formRef}
        noValidate
        onSubmit={definitionForm.onSubmit(handleSubmit)}
      >
        <Stack gap="md" mb="lg">
          <Group justify="space-between" align="flex-end" wrap="nowrap">
            <Box
              style={{
                flex: 1,
                maxWidth: editorMode === 'json' ? 420 : undefined,
              }}
            >
              <TextInput
                label="Control name"
                placeholder="Enter control name"
                size="sm"
                required
                {...definitionForm.getInputProps('name')}
              />
            </Box>
            <Group gap="xs" align="center">
              {definitionStatusLabel ? (
                <Text size="xs" c={definitionStatusColor}>
                  {definitionStatusLabel}
                </Text>
              ) : null}
              <Tooltip
                label="Form: guided editing. Full JSON: direct control over the definition."
                openDelay={600}
              >
                <SegmentedControl
                  value={editorMode}
                  onChange={handleEditorModeChange}
                  disabled={isDefinitionJsonParseError}
                  data={[
                    { value: 'form', label: 'Form' },
                    { value: 'json', label: 'Full JSON' },
                  ]}
                  size="xs"
                />
              </Tooltip>
            </Group>
          </Group>

          {editorMode === 'json' ? (
            <Text size="sm" c="dimmed">
              Edit the full control definition below. Control name stays
              separate.
            </Text>
          ) : (
            <TextInput
              label="Description"
              placeholder="Optional description of what this control does"
              size="sm"
              {...definitionForm.getInputProps('description')}
            />
          )}
        </Stack>

        {editorMode === 'json' ? (
          <Paper withBorder radius="sm" p={16}>
            <JsonEditorMonaco
              jsonText={definitionJsonText}
              handleJsonChange={handleDefinitionJsonChange}
              jsonError={definitionJsonError}
              setJsonError={setDefinitionJsonError}
              validationError={definitionValidationError}
              setValidationError={setDefinitionValidationError}
              onValidateConfig={validateDefinitionJson}
              onValidationStatusChange={setDefinitionValidationStatus}
              height={JSON_EDITOR_HEIGHT}
              label="Control definition (JSON)"
              tooltip="Edit the raw control definition as JSON. Control name remains outside this editor."
              helperText="Enter the raw control definition only. Do not wrap it in data, name, id, or control objects."
              testId="control-json-textarea"
              editorMode="control"
              schema={controlSchemaResponse?.schema ?? null}
              evaluators={availableEvaluators}
              steps={steps}
            />
          </Paper>
        ) : (
          <Grid gutter="xl">
            <Grid.Col span={4}>
              <ControlDefinitionForm
                form={definitionForm}
                steps={steps}
                disableSelectorPath={!canEditLeafCondition}
              />
            </Grid.Col>

            <Grid.Col span={8}>
              {canEditLeafCondition ? (
                <EvaluatorConfigSection
                  config={evaluatorConfig}
                  evaluatorForm={evaluatorForm}
                  formComponent={formComponent}
                  height={EVALUATOR_CONFIG_HEIGHT}
                  onConfigChange={syncJsonToForm}
                  onValidateConfig={validateEvaluatorConfig}
                  activeEvaluatorId={evaluatorId}
                  activeEvaluatorSchema={activeEvaluatorOption?.configSchema}
                />
              ) : (
                <Alert color="blue" variant="light" title="Composite condition">
                  This control uses a composite boolean condition tree. Switch
                  to Full JSON mode to edit the condition.
                </Alert>
              )}
            </Grid.Col>
          </Grid>
        )}

        {apiError ? (
          <>
            <Divider mt="xl" mb="md" />
            <ApiErrorAlert
              error={apiError}
              unmappedErrors={unmappedErrors}
              onClose={() => setApiError(null)}
            />
          </>
        ) : null}

        <Divider mt="xl" mb="md" />
        <Group justify="flex-end">
          <Button
            variant="outline"
            onClick={handleClose}
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
