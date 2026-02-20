import { Box, Divider, Grid, Group, Text, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { modals } from '@mantine/modals';
import { Button } from '@rungalileo/jupiter-ds';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { isApiError } from '@/core/api/errors';
import type { Control, ProblemDetail } from '@/core/api/types';
import { getEvaluator } from '@/core/evaluators';
import { useAddControlToAgent } from '@/core/hooks/query-hooks/use-add-control-to-agent';
import { useAgent } from '@/core/hooks/query-hooks/use-agent';
import { useUpdateControl } from '@/core/hooks/query-hooks/use-update-control';
import { useValidateControlData } from '@/core/hooks/query-hooks/use-validate-control-data';

import { ApiErrorAlert } from './api-error-alert';
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
  // Fetch agent data to get steps - React Query will dedupe requests
  const { data: agentResponse } = useAgent(agentId);
  const steps = agentResponse?.steps ?? [];
  // API error state
  const [apiError, setApiError] = useState<ProblemDetail | null>(null);
  // Errors that couldn't be mapped to form fields (shown in Alert)
  const [unmappedErrors, setUnmappedErrors] = useState<
    Array<{ field: string | null; message: string }>
  >([]);

  // Mutation hooks
  const updateControl = useUpdateControl();
  const addControlToAgent = useAddControlToAgent();
  const { mutateAsync: validateControlDataAsync } = useValidateControlData();
  const isCreating = mode === 'create';
  const isPending = isCreating
    ? addControlToAgent.isPending
    : updateControl.isPending;

  // Track which evaluator the evaluator form has been initialized for
  const formInitializedForEvaluator = useRef<string>('');

  // Get evaluator for this control
  const evaluatorId = control.control.evaluator.name || '';
  const evaluator = useMemo(() => getEvaluator(evaluatorId), [evaluatorId]);

  // Control definition form
  const definitionForm = useForm<ControlDefinitionFormValues>({
    initialValues: {
      name: '',
      enabled: true,
      step_types: ['llm'],
      stages: ['post'],
      step_names: '',
      step_name_regex: '',
      step_name_mode: 'names',
      selector_path: '*',
      action_decision: 'deny',
      execution: 'server',
    },
    validate: {
      name: (value) => (!value?.trim() ? 'Control name is required' : null),
      selector_path: (value) =>
        !value?.trim() ? 'Selector path is required' : null,
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

  // Sync JSON to form
  const syncJsonToForm = (config: Record<string, unknown>) => {
    if (evaluator) {
      evaluatorForm.setValues(evaluator.fromConfig(config));
    }
  };

  const buildControlDefinition = useCallback(
    (
      values: ControlDefinitionFormValues,
      finalConfig: Record<string, unknown>
    ) => {
      const stepTypes = values.step_types
        .map((value) => value.trim())
        .filter(Boolean);
      const stepNames = values.step_names
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean);
      const stepNameRegex = values.step_name_regex.trim();
      const isRegexMode = values.step_name_mode === 'regex';

      return {
        ...control.control,
        enabled: values.enabled,
        execution: values.execution,
        scope: {
          step_types: stepTypes.length > 0 ? stepTypes : undefined,
          step_names:
            !isRegexMode && stepNames.length > 0 ? stepNames : undefined,
          step_name_regex: isRegexMode ? stepNameRegex || undefined : undefined,
          stages: values.stages.length > 0 ? values.stages : undefined,
        },
        selector: { ...control.control.selector, path: values.selector_path },
        action: { decision: values.action_decision },
        evaluator: { ...control.control.evaluator, config: finalConfig },
      };
    },
    [control.control]
  );

  const buildDefinitionForValidation = useCallback(
    (finalConfig: Record<string, unknown>) => ({
      ...control.control,
      evaluator: { ...control.control.evaluator, config: finalConfig },
    }),
    [control.control]
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

  const { isJsonInvalid, reset } = evaluatorConfig;

  // Reset view mode and errors when evaluator changes
  useEffect(() => {
    reset();
    setApiError(null);
    setUnmappedErrors([]);
  }, [reset, evaluatorId]);

  // Load control data into forms
  useEffect(() => {
    if (control && evaluator) {
      const scope = control.control.scope ?? {};
      const stepNamesValue = (scope.step_names ?? []).join(', ');
      const stepRegexValue = scope.step_name_regex ?? '';
      const stepNameMode =
        stepRegexValue && !stepNamesValue ? 'regex' : 'names';
      definitionForm.setValues({
        name: control.name,
        enabled: control.control.enabled,
        step_types: scope.step_types ?? [],
        stages: scope.stages ?? [],
        step_names: stepNamesValue,
        step_name_regex: stepRegexValue,
        step_name_mode: stepNameMode,
        selector_path: control.control.selector.path ?? '*',
        action_decision: control.control.action.decision,
        execution: control.control.execution ?? 'server',
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

    if (evaluatorConfig.configViewMode === 'json') {
      const jsonConfig = evaluatorConfig.getJsonConfig();
      if (!jsonConfig) return;
      finalConfig = jsonConfig;
    } else {
      // Validate evaluator form
      const validation = evaluatorForm.validate();
      if (validation.hasErrors) return;
      finalConfig = getEvaluatorConfig();
    }

    const definition = buildControlDefinition(values, finalConfig);

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
              problemDetail.error_code === 'CONTROL_NAME_EXISTS' ||
              (problemDetail.detail?.toLowerCase().includes('name') &&
                problemDetail.detail
                  ?.toLowerCase()
                  .includes('already exists'))) &&
            !problemDetail.errors?.some((e) => e.field === 'name');

          if (isNameExistsError) {
            // Set error directly on the name field
            definitionForm.setFieldError(
              'name',
              problemDetail.detail || 'Control name already exists'
            );
            // Don't show it in the alert since it's now on the field
            setApiError(null);
            setUnmappedErrors([]);
          } else {
            setApiError(problemDetail);

            if (problemDetail.errors) {
              if (evaluatorConfig.configViewMode === 'form') {
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

    modals.openConfirmModal({
      title: isCreating ? 'Create control?' : 'Save changes?',
      children: (
        <Text size="sm" c="dimmed">
          {isCreating
            ? 'This will add the new control to the agent.'
            : 'This will update the control configuration.'}
        </Text>
      ),
      labels: { confirm: 'Confirm', cancel: 'Cancel' },
      confirmProps: {
        variant: 'filled',
        color: 'violet',
        size: 'sm',
        className: 'confirm-modal-confirm-btn',
      },
      cancelProps: { variant: 'default', size: 'sm' },
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
          {...definitionForm.getInputProps('name')}
        />

        <Grid gutter="xl">
          <Grid.Col span={4}>
            <ControlDefinitionForm form={definitionForm} steps={steps} />
          </Grid.Col>

          <Grid.Col span={8}>
            <EvaluatorConfigSection
              config={evaluatorConfig}
              evaluatorForm={evaluatorForm}
              formComponent={FormComponent}
              height={EVALUATOR_CONFIG_HEIGHT}
              onConfigChange={syncJsonToForm}
              onValidateConfig={validateEvaluatorConfig}
            />
          </Grid.Col>
        </Grid>

        {/* API Error Alert */}
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
            disabled={isJsonInvalid}
          >
            Save
          </Button>
        </Group>
      </form>
    </Box>
  );
};
