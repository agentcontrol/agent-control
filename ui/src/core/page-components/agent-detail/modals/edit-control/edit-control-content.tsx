import { Box, Divider, Grid, Group, Text, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { Button } from '@rungalileo/jupiter-ds';
import { useCallback, useEffect, useState } from 'react';

import { isApiError } from '@/core/api/errors';
import type {
  Control,
  ControlDefinition,
  ProblemDetail,
  ValidationErrorItem,
} from '@/core/api/types';
import { useAddControlToAgent } from '@/core/hooks/query-hooks/use-add-control-to-agent';
import { useAgent } from '@/core/hooks/query-hooks/use-agent';
import { useUpdateControl } from '@/core/hooks/query-hooks/use-update-control';
import { useUpdateControlMetadata } from '@/core/hooks/query-hooks/use-update-control-metadata';
import { useValidateControlData } from '@/core/hooks/query-hooks/use-validate-control-data';

import { ApiErrorAlert } from './api-error-alert';
import {
  createLeafNode,
  deserializeConditionNode,
  serializeConditionNode,
  type ConditionBuilderError,
  type ConditionBuilderNode,
  validateConditionTree,
} from './condition-builder';
import { ConditionTreeEditor } from './condition-tree-editor';
import { ControlDefinitionForm } from './control-definition-form';
import type { ControlDefinitionFormValues, EditControlMode } from './types';
import { applyApiErrorsToForms } from './utils';

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
  const [conditionNode, setConditionNode] = useState<ConditionBuilderNode>(
    createLeafNode()
  );
  const [conditionErrors, setConditionErrors] = useState<
    ValidationErrorItem[] | ConditionBuilderError[]
  >([]);

  const updateControl = useUpdateControl();
  const updateControlMetadata = useUpdateControlMetadata();
  const addControlToAgent = useAddControlToAgent();
  const { mutateAsync: validateControlDataAsync } = useValidateControlData();
  const isCreating = mode === 'create';
  const isPending = isCreating
    ? addControlToAgent.isPending
    : updateControl.isPending || updateControlMetadata.isPending;

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
      action_decision: 'deny',
      action_steering_context: '',
      execution: 'server',
    },
    validate: {
      name: (value) => (!value?.trim() ? 'Control name is required' : null),
    },
  });

  const buildControlDefinition = useCallback(
    (values: ControlDefinitionFormValues): ControlDefinition => {
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
        condition: serializeConditionNode(conditionNode),
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
        tags: control.control.tags ?? [],
      };
    },
    [conditionNode, control.control.tags]
  );

  useEffect(() => {
    if (definitionForm.values.action_decision !== 'steer') {
      definitionForm.setFieldValue('action_steering_context', '');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [definitionForm.values.action_decision]);

  useEffect(() => {
    if (!control) {
      return;
    }

    const scope = control.control.scope ?? {};
    const stepNamesValue = (scope.step_names ?? []).join(', ');
    const stepRegexValue = scope.step_name_regex ?? '';
    const stepNameMode =
      stepRegexValue && !stepNamesValue ? 'regex' : 'names';

    definitionForm.setValues({
      name: control.name,
      description: control.control.description ?? '',
      enabled: control.control.enabled,
      step_types: scope.step_types ?? [],
      stages: scope.stages ?? [],
      step_names: stepNamesValue,
      step_name_regex: stepRegexValue,
      step_name_mode: stepNameMode,
      action_decision: control.control.action.decision,
      action_steering_context:
        control.control.action.decision === 'steer'
          ? (control.control.action.steering_context?.message ?? '')
          : '',
      execution: control.control.execution ?? 'server',
    });
    setConditionNode(
      control.control.condition
        ? deserializeConditionNode(control.control.condition)
        : createLeafNode()
    );
    setConditionErrors([]);
    setApiError(null);
    setUnmappedErrors([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [control]);

  const handleSubmit = async (values: ControlDefinitionFormValues) => {
    setApiError(null);
    setUnmappedErrors([]);
    setConditionErrors([]);
    definitionForm.clearErrors();

    const localConditionErrors = validateConditionTree(conditionNode);
    if (localConditionErrors.length > 0) {
      setConditionErrors(localConditionErrors);
      return;
    }

    if (
      values.action_decision === 'steer' &&
      conditionNode.kind !== 'leaf' &&
      !values.action_steering_context?.trim()
    ) {
      definitionForm.setFieldError(
        'action_steering_context',
        'Composite steer controls require steering context'
      );
      return;
    }

    const definition = buildControlDefinition(values);

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
            message: `"${values.name}" has been added to this agent.`,
            color: 'green',
          });
        } else {
          const trimmedName = values.name.trim();
          const nameChanged = trimmedName && trimmedName !== control.name;

          if (nameChanged) {
            try {
              await updateControlMetadata.mutateAsync({
                agentId,
                controlId: control.id,
                data: { name: trimmedName },
              });
            } catch (renameError) {
              if (
                isApiError(renameError) &&
                (renameError.problemDetail.status === 409 ||
                  renameError.problemDetail.error_code ===
                    'CONTROL_NAME_CONFLICT')
              ) {
                definitionForm.setFieldError(
                  'name',
                  renameError.problemDetail.detail ||
                    'Control name already exists'
                );
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
            message: `"${trimmedName}" has been saved.`,
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

          const definitionErrors = problemDetail.errors?.filter(
            (item) => !item.field?.startsWith('data.condition')
          );
          const treeErrors =
            problemDetail.errors?.filter((item) =>
              item.field?.startsWith('data.condition')
            ) ?? [];

          if (treeErrors.length > 0) {
            setConditionErrors(treeErrors);
          }

          const unmapped = applyApiErrorsToForms(
            definitionErrors,
            definitionForm,
            null
          );
          setUnmappedErrors(
            unmapped.map((item) => ({
              field: item.field,
              message: item.message,
            }))
          );
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
            <ControlDefinitionForm form={definitionForm} steps={steps} />
          </Grid.Col>

          <Grid.Col span={8}>
            <ConditionTreeEditor
              rootNode={conditionNode}
              onChange={setConditionNode}
              errors={conditionErrors}
            />
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
