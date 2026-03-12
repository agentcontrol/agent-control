import {
  Alert,
  Autocomplete,
  Badge,
  Button,
  Group,
  Paper,
  Select,
  Stack,
  Text,
  Textarea,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import {
  IconAlertCircle,
  IconArrowDown,
  IconArrowUp,
  IconBraces,
  IconPlus,
  IconTrash,
} from '@tabler/icons-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import type { ValidationErrorItem } from '@/core/api/types';
import { evaluators, getEvaluator } from '@/core/evaluators';

import {
  type ConditionBuilderError,
  type ConditionBuilderLeaf,
  type ConditionBuilderNode,
  createGroupNode,
  createLeafNode,
  deleteConditionNode,
  getConditionErrorsForPath,
  insertChildNode,
  moveConditionNode,
  replaceConditionNode,
  unwrapNotConditionNode,
  wrapConditionNodeWithNot,
} from './condition-builder';

type ConditionTreeEditorProps = {
  rootNode: ConditionBuilderNode;
  onChange: (node: ConditionBuilderNode) => void;
  errors: ValidationErrorItem[] | ConditionBuilderError[];
  warningDepth?: number;
  maxDepth?: number;
};

type LeafEvaluatorFormProps = {
  node: ConditionBuilderLeaf;
  path: string;
  errors: string[];
  onChange: (node: ConditionBuilderLeaf) => void;
};

const SELECTOR_OPTIONS = ['*', 'input', 'output', 'name', 'type', 'context'];

function LeafEvaluatorForm({
  node,
  path,
  errors,
  onChange,
}: LeafEvaluatorFormProps) {
  const evaluator = getEvaluator(node.evaluatorName);
  const skipConfigSyncRef = useRef(false);
  const [jsonText, setJsonText] = useState(() =>
    JSON.stringify(node.config, null, 2)
  );
  const [jsonError, setJsonError] = useState<string | null>(null);
  const configSignature = useMemo(
    () => JSON.stringify(node.config),
    [node.config]
  );

  const form = useForm({
    initialValues: evaluator?.fromConfig(node.config) ?? {},
    validate: evaluator?.validate,
  });

  useEffect(() => {
    setJsonText(JSON.stringify(node.config, null, 2));
    setJsonError(null);
  }, [configSignature, node.config]);

  useEffect(() => {
    if (!evaluator) {
      return;
    }
    skipConfigSyncRef.current = true;
    form.setValues(evaluator.fromConfig(node.config));
    form.clearErrors();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [evaluator?.id, configSignature]);

  useEffect(() => {
    if (!evaluator) {
      return;
    }
    if (skipConfigSyncRef.current) {
      skipConfigSyncRef.current = false;
      return;
    }
    const nextConfig = evaluator.toConfig(form.values);
    if (JSON.stringify(nextConfig) === configSignature) {
      return;
    }
    onChange({
      ...node,
      config: nextConfig,
    });
  }, [configSignature, evaluator, form.values, node, onChange]);

  if (!evaluator) {
    return (
      <Stack gap="xs">
        <Textarea
          label="Evaluator config (JSON)"
          minRows={6}
          value={jsonText}
          onChange={(event) => {
            const nextValue = event.currentTarget.value;
            setJsonText(nextValue);
            try {
              const parsed = JSON.parse(nextValue) as Record<string, unknown>;
              setJsonError(null);
              onChange({
                ...node,
                config: parsed,
              });
            } catch (error) {
              setJsonError(
                error instanceof Error ? error.message : 'Invalid JSON'
              );
            }
          }}
        />
        {jsonError ? (
          <Text size="xs" c="red">
            {jsonError}
          </Text>
        ) : null}
        <Text size="xs" c="dimmed">
          No structured form is available for evaluator `{node.evaluatorName}`.
        </Text>
        {errors.map((error) => (
          <Text key={`${path}-${error}`} size="xs" c="red">
            {error}
          </Text>
        ))}
      </Stack>
    );
  }

  const FormComponent = evaluator.FormComponent;
  return (
    <Stack gap="xs">
      <FormComponent key={`${node.id}:${node.evaluatorName}`} form={form} />
      {errors.map((error) => (
        <Text key={`${path}-${error}`} size="xs" c="red">
          {error}
        </Text>
      ))}
    </Stack>
  );
}

type ConditionNodeCardProps = {
  node: ConditionBuilderNode;
  path: string;
  depth: number;
  warningDepth: number;
  maxDepth: number;
  errors: ValidationErrorItem[] | ConditionBuilderError[];
  canMoveUp: boolean;
  canMoveDown: boolean;
  onChange: (node: ConditionBuilderNode) => void;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
};

function ConditionNodeCard({
  node,
  path,
  depth,
  warningDepth,
  maxDepth,
  errors,
  canMoveUp,
  canMoveDown,
  onChange,
  onDelete,
  onMoveUp,
  onMoveDown,
}: ConditionNodeCardProps) {
  const nodeErrors = getConditionErrorsForPath(errors, path);
  const currentDepthWarning = depth >= warningDepth;
  const evaluatorOptions = [
    ...evaluators.map((evaluator) => ({
      value: evaluator.id,
      label: evaluator.displayName,
    })),
    ...(getEvaluator(node.kind === 'leaf' ? node.evaluatorName : '') ||
    node.kind !== 'leaf'
      ? []
      : [{ value: node.evaluatorName, label: node.evaluatorName }]),
  ];

  return (
    <Paper
      withBorder
      radius="md"
      p="md"
      data-condition-path={path}
      style={{ backgroundColor: 'var(--mantine-color-default)' }}
    >
      <Stack gap="md">
        <Group justify="space-between" align="flex-start">
          <Group gap="xs">
            <Badge variant="light">{node.kind.toUpperCase()}</Badge>
            <Text size="sm" c="dimmed">
              {path.replace('data.', '')}
            </Text>
          </Group>
          <Group gap="xs">
            <Button
              variant="light"
              size="xs"
              leftSection={<IconArrowUp size={14} />}
              disabled={!canMoveUp}
              onClick={onMoveUp}
            >
              Move up
            </Button>
            <Button
              variant="light"
              size="xs"
              leftSection={<IconArrowDown size={14} />}
              disabled={!canMoveDown}
              onClick={onMoveDown}
            >
              Move down
            </Button>
            <Button
              variant="light"
              size="xs"
              leftSection={<IconBraces size={14} />}
              onClick={() =>
                onChange({
                  kind: 'not',
                  id: node.id,
                  child: { ...node, id: `${node.id}-wrapped` },
                })
              }
            >
              Replace with NOT
            </Button>
            <Button
              variant="light"
              color="red"
              size="xs"
              leftSection={<IconTrash size={14} />}
              onClick={onDelete}
            >
              Delete
            </Button>
          </Group>
        </Group>

        {currentDepthWarning ? (
          <Text size="xs" c={depth > maxDepth ? 'red' : 'orange'}>
            Depth {depth} of {maxDepth}. Deep trees are harder to reason about.
          </Text>
        ) : null}

        {node.kind === 'leaf' ? (
          <Stack gap="sm">
            <Group grow align="flex-start">
              <Autocomplete
                label="Selector path"
                data={SELECTOR_OPTIONS}
                value={node.selectorPath}
                onChange={(value) =>
                  onChange({
                    ...node,
                    selectorPath: value,
                  })
                }
              />
              <Select
                label="Evaluator"
                data={evaluatorOptions}
                value={node.evaluatorName}
                onChange={(value) => {
                  const nextEvaluator = value ?? node.evaluatorName;
                  const evaluator = getEvaluator(nextEvaluator);
                  onChange({
                    ...node,
                    evaluatorName: nextEvaluator,
                    config:
                      evaluator?.toConfig(evaluator.initialValues) ??
                      node.config,
                  });
                }}
              />
            </Group>

            <Group gap="xs">
              <Button
                variant="default"
                size="xs"
                leftSection={<IconPlus size={14} />}
                onClick={() =>
                  onChange(createGroupNode('and', [node, createLeafNode()]))
                }
              >
                Replace with AND group
              </Button>
              <Button
                variant="default"
                size="xs"
                leftSection={<IconPlus size={14} />}
                onClick={() =>
                  onChange(createGroupNode('or', [node, createLeafNode()]))
                }
              >
                Replace with OR group
              </Button>
              <Button
                variant="default"
                size="xs"
                onClick={() =>
                  onChange(wrapConditionNodeWithNot(node, node.id))
                }
              >
                Wrap with NOT
              </Button>
            </Group>

            <LeafEvaluatorForm
              node={node}
              path={path}
              errors={nodeErrors}
              onChange={onChange}
            />
          </Stack>
        ) : null}

        {node.kind === 'not' ? (
          <Stack gap="sm">
            <Group>
              <Button
                variant="default"
                size="xs"
                onClick={() => onChange(unwrapNotConditionNode(node, node.id))}
              >
                Unwrap NOT
              </Button>
            </Group>
            <ConditionNodeCard
              node={node.child}
              path={`${path}.not`}
              depth={depth + 1}
              warningDepth={warningDepth}
              maxDepth={maxDepth}
              errors={errors}
              canMoveUp={false}
              canMoveDown={false}
              onChange={(child) => onChange({ ...node, child })}
              onDelete={() => onChange(createLeafNode())}
              onMoveUp={() => undefined}
              onMoveDown={() => undefined}
            />
          </Stack>
        ) : null}

        {(node.kind === 'and' || node.kind === 'or') && (
          <Stack gap="sm">
            <Group justify="space-between" align="center">
              <Select
                label="Operator"
                data={[
                  { value: 'and', label: 'AND' },
                  { value: 'or', label: 'OR' },
                ]}
                value={node.kind}
                onChange={(value) =>
                  onChange({
                    ...node,
                    kind: (value as 'and' | 'or') || node.kind,
                  })
                }
                w={140}
              />
              <Group gap="xs">
                <Button
                  variant="default"
                  size="xs"
                  leftSection={<IconPlus size={14} />}
                  onClick={() =>
                    onChange(insertChildNode(node, node.id, createLeafNode()))
                  }
                >
                  Add leaf
                </Button>
                <Button
                  variant="default"
                  size="xs"
                  leftSection={<IconPlus size={14} />}
                  onClick={() =>
                    onChange(
                      insertChildNode(node, node.id, createGroupNode('and'))
                    )
                  }
                >
                  Add AND group
                </Button>
                <Button
                  variant="default"
                  size="xs"
                  leftSection={<IconPlus size={14} />}
                  onClick={() =>
                    onChange(
                      insertChildNode(node, node.id, createGroupNode('or'))
                    )
                  }
                >
                  Add OR group
                </Button>
              </Group>
            </Group>

            {node.children.map((child, index) => (
              <ConditionNodeCard
                key={child.id}
                node={child}
                path={`${path}.${node.kind}[${index}]`}
                depth={depth + 1}
                warningDepth={warningDepth}
                maxDepth={maxDepth}
                errors={errors}
                canMoveUp={index > 0}
                canMoveDown={index < node.children.length - 1}
                onChange={(nextChild) =>
                  onChange(replaceConditionNode(node, child.id, nextChild))
                }
                onDelete={() => onChange(deleteConditionNode(node, child.id))}
                onMoveUp={() =>
                  onChange(moveConditionNode(node, child.id, 'up'))
                }
                onMoveDown={() =>
                  onChange(moveConditionNode(node, child.id, 'down'))
                }
              />
            ))}
          </Stack>
        )}

        {nodeErrors.length > 0 && node.kind !== 'leaf' ? (
          <Alert color="red" icon={<IconAlertCircle size={16} />}>
            <Stack gap={4}>
              {nodeErrors.map((error) => (
                <Text key={`${path}-${error}`} size="sm">
                  {error}
                </Text>
              ))}
            </Stack>
          </Alert>
        ) : null}
      </Stack>
    </Paper>
  );
}

export function ConditionTreeEditor({
  rootNode,
  onChange,
  errors,
  warningDepth = 4,
  maxDepth = 6,
}: ConditionTreeEditorProps) {
  const scrollToError = (field: string | null) => {
    if (!field) {
      return;
    }
    const nodePath = field
      .replace(/\.selector\..*$/, '')
      .replace(/\.evaluator\..*$/, '')
      .replace(/\.action\..*$/, '');
    const element = document.querySelector(
      `[data-condition-path="${nodePath.replace(/"/g, '\\"')}"]`
    );
    if (element instanceof HTMLElement) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  };

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Text size="sm" fw={500}>
          Condition tree
        </Text>
        <Text size="xs" c="dimmed">
          Compose leaves with AND / OR / NOT. Execution order is left to right.
        </Text>
      </Group>

      {errors.length > 0 ? (
        <Alert color="red" icon={<IconAlertCircle size={16} />}>
          <Stack gap="xs">
            <Text size="sm" fw={500}>
              Fix these condition errors
            </Text>
            {errors.map((error) => (
              <Button
                key={`${error.field}-${error.message}`}
                variant="subtle"
                justify="flex-start"
                color="red"
                size="xs"
                onClick={() => scrollToError(error.field)}
              >
                {error.field ? `${error.field}: ` : ''}
                {error.message}
              </Button>
            ))}
          </Stack>
        </Alert>
      ) : null}

      <ConditionNodeCard
        node={rootNode}
        path="data.condition"
        depth={1}
        warningDepth={warningDepth}
        maxDepth={maxDepth}
        errors={errors}
        canMoveUp={false}
        canMoveDown={false}
        onChange={onChange}
        onDelete={() => onChange(createLeafNode())}
        onMoveUp={() => undefined}
        onMoveDown={() => undefined}
      />
    </Stack>
  );
}
