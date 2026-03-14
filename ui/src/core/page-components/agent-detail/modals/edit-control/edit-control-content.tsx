import {
  Alert,
  Box,
  Divider,
  Grid,
  Group,
  Text,
  TextInput,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { Button } from '@rungalileo/jupiter-ds';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { isApiError } from '@/core/api/errors';
import type {
  Control,
  ControlDefinition,
  ProblemDetail,
} from '@/core/api/types';
import { useAddControlToAgent } from '@/core/hooks/query-hooks/use-add-control-to-agent';
import { useAgent } from '@/core/hooks/query-hooks/use-agent';
import { useUpdateControl } from '@/core/hooks/query-hooks/use-update-control';
import { useUpdateControlMetadata } from '@/core/hooks/query-hooks/use-update-control-metadata';
import { useValidateControlData } from '@/core/hooks/query-hooks/use-validate-control-data';
import { openActionConfirmModal } from '@/core/utils/modals';

import { ApiErrorAlert } from './api-error-alert';
import {
  buildEditableCondition,
  getControlConditionState,
} from './control-condition';
import { ControlDefinitionForm } from './control-definition-form';
import { EvaluatorConfigSection } from './evaluator-config-section';
import type { ControlDefinitionFormValues, EditControlMode } from './types';
import { useEvaluatorConfigState } from './use-evaluator-config-state';
import { applyApiErrorsToForms } from './utils';

const EVALUATOR_CONFIG_HEIGHT = 450;

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
};

export const EditControlContent = ({
  control,
  agentId,
  mode = 'edit',
  onClose,
  onSuccess,
}: EditControlContentProps) => {
  const { data: agentResponse } = useAgent(agentId);
  const steps = agentResponse?.steps ?? [];

  const [apiError, setApiError] = useState<ProblemDetail | null>(null);
  const [unmappedErrors, setUnmappedErrors] = useState<
    Array<{ field: string | null; message: string }>
  >([]);

  const updateControl = useUpdateControl();
  const updateControlMetadata = useUpdateControlMetadata();
  const addControlToAgent = useAddControlToAgent();
  const { mutateAsync: validateControlDataAsync } = useValidateControlData();
  const isCreating = mode === 'create';
  const isPending = isCreating
    ? addControlToAgent.isPending
    : updateControl.isPending || updateControlMetadata.isPending;

  const formInitializedForEvaluator = useRef<string>('');
  const {
    leafCondition,
    evaluatorId,
    evaluator,
    canEditLeafCondition,
    conditionEditingMessage,
  } = useMemo(
    () => getControlConditionState(control.control),
    [control.control]
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
        if (!canEditLeafCondition) {
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

  const buildCondition = useCallback(
    (
      values: ControlDefinitionFormValues,
      finalConfig: Record<string, unknown>
    ): ControlDefinition['condition'] => {
      return buildEditableCondition(
        control.control,
        leafCondition,
        values.selector_path.trim(),
        finalConfig
      );
    },
    [control.control, leafCondition]
  );

  const buildControlDefinition = useCallback(
    (
      values: ControlDefinitionFormValues,
      finalConfig: Record<string, unknown>
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
        condition: buildCondition(values, finalConfig),
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
        tags: control.control.tags,
      };
    },
    [buildCondition, control.control.tags]
  );

  const buildDefinitionForValidation = useCallback(
    (finalConfig: Record<string, unknown>): ControlDefinition => ({
      ...control.control,
      condition: buildCondition(definitionForm.values, finalConfig),
    }),
    [buildCondition, control.control, definitionForm.values]
  );

  const validateEvaluatorConfig = useCallback(
    async (
      config: Record<string, unknown>,
      options?: { signal?: AbortSignal }
    ) => {
      await validateControlDataAsync({
        definition: buildDefinitionForValidation(config),
        signal: options?.signal,
      });
    },
    [buildDefinitionForValidation, validateControlDataAsync]
  );

  const evaluatorConfig = useEvaluatorConfigState({
    getConfigFromForm: getEvaluatorConfig,
    onConfigChange: syncJsonToForm,
    onValidateConfig: validateEvaluatorConfig,
  });

  const { reset } = evaluatorConfig;

  useEffect(() => {
    if (definitionForm.values.action_decision !== 'steer') {
      definitionForm.setFieldValue('action_steering_context', '');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [definitionForm.values.action_decision]);

  useEffect(() => {
    reset();
    setApiError(null);
    setUnmappedErrors([]);
    formInitializedForEvaluator.current = '';
  }, [reset, evaluatorId, control.id]);

  useEffect(() => {
    const scope = control.control.scope ?? {};
    const stepNamesValue = (scope.step_names ?? []).join(', ');
    const stepRegexValue = scope.step_name_regex ?? '';
    const stepNameMode = stepRegexValue && !stepNamesValue ? 'regex' : 'names';

    definitionForm.setValues({
      name: control.name,
      description: control.control.description ?? '',
      enabled: control.control.enabled,
      step_types: scope.step_types ?? [],
      stages: scope.stages ?? [],
      step_names: stepNamesValue,
      step_name_regex: stepRegexValue,
      step_name_mode: stepNameMode,
      selector_path: leafCondition?.selectorPath ?? '*',
      action_decision: control.control.action.decision,
      action_steering_context:
        control.control.action.decision === 'steer'
          ? (control.control.action.steering_context?.message ?? '')
          : '',
      execution: control.control.execution ?? 'server',
    });

    if (leafCondition && evaluator) {
      evaluatorForm.setValues(
        evaluator.fromConfig(leafCondition.evaluatorConfig)
      );
      formInitializedForEvaluator.current = evaluatorId;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [control, evaluator, evaluatorId, leafCondition]);

  const handleSubmit = async (values: ControlDefinitionFormValues) => {
    setApiError(null);
    setUnmappedErrors([]);
    definitionForm.clearErrors();
    evaluatorForm.clearErrors();

    if (
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

    let finalConfig: Record<string, unknown> =
      leafCondition?.evaluatorConfig ?? {};

    if (canEditLeafCondition) {
      if (evaluatorConfig.configViewMode === 'json') {
        const jsonConfig = evaluatorConfig.getJsonConfig();
        if (!jsonConfig) return;
        finalConfig = jsonConfig;
      } else {
        const validation = evaluatorForm.validate();
        if (validation.hasErrors) return;
        finalConfig = getEvaluatorConfig();
      }
    }

    const definition = buildControlDefinition(values, finalConfig);

    const runSave = async () => {
      try {
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
            if (evaluatorConfig.configViewMode === 'form') {
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

    openActionConfirmModal({
      title: isCreating ? 'Create control?' : 'Save changes?',
      children: (
        <Text size="sm" c="dimmed">
          {isCreating
            ? 'This will add the new control to the agent.'
            : 'This will update the control configuration.'}
        </Text>
      ),
      onConfirm: runSave,
    });
  };

  const formComponent = evaluator?.FormComponent;

  return (
    <Box>
      <form onSubmit={definitionForm.onSubmit(handleSubmit)}>
        <Grid gutter="xl" mb="lg">
          <Grid.Col span={6}>
            <TextInput
              label="Control name"
              placeholder="Enter control name"
              size="sm"
              required
              {...definitionForm.getInputProps('name')}
            />
          </Grid.Col>
          <Grid.Col span={6}>
            <TextInput
              label="Description"
              placeholder="Optional description of what this control does"
              size="sm"
              {...definitionForm.getInputProps('description')}
            />
          </Grid.Col>
        </Grid>

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
              />
            ) : (
              <Alert
                color="blue"
                variant="light"
                title="Condition editing unavailable"
              >
                {conditionEditingMessage}
              </Alert>
            )}
          </Grid.Col>
        </Grid>

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
