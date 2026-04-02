import {
  findNodeAtLocation,
  type Node as JsonNode,
  parseTree,
} from 'jsonc-parser';

import type {
  JsonEditorEvaluatorOption,
  JsonEditorMode,
} from '@/core/page-components/agent-detail/modals/edit-control/types';

import {
  asSchema,
  getSchemaDefault,
  getSchemaEnumValues,
  getSchemaProperties,
  getSchemaRequiredProperties,
  getSchemaType,
  normalizeSchema,
} from './schema';
import type { JsonEditorTextEdit } from './types';

type EvaluatorNodeInfo = {
  name: string;
  nameNode: JsonNode;
  configNode: JsonNode | undefined;
};

function collectEvaluatorNames(
  node: JsonNode | undefined,
  result: Map<string, EvaluatorNodeInfo>
) {
  if (!node || node.type !== 'object' || !node.children) return;

  const evaluatorNode = findNodeAtLocation(node, ['evaluator']);
  if (evaluatorNode?.type === 'object') {
    const nameNode = findNodeAtLocation(evaluatorNode, ['name']);
    const configNode = findNodeAtLocation(evaluatorNode, ['config']);
    if (nameNode && typeof nameNode.value === 'string') {
      result.set(`${nameNode.offset}`, {
        name: nameNode.value,
        nameNode,
        configNode,
      });
    }
  }

  for (const key of ['and', 'or'] as const) {
    const arrayNode = findNodeAtLocation(node, [key]);
    if (arrayNode?.type === 'array' && arrayNode.children) {
      for (const child of arrayNode.children)
        collectEvaluatorNames(child, result);
    }
  }

  const notNode = findNodeAtLocation(node, ['not']);
  if (notNode?.type === 'object') collectEvaluatorNames(notNode, result);
}

export function extractEvaluatorNames(text: string): Map<string, string> {
  const tree = parseTree(text);
  if (!tree) return new Map();
  const conditionNode = findNodeAtLocation(tree, ['condition']);
  const result = new Map<string, EvaluatorNodeInfo>();
  collectEvaluatorNames(conditionNode, result);
  const names = new Map<string, string>();
  for (const [key, info] of result) names.set(key, info.name);
  return names;
}

function getDefaultValueForSchema(
  propSchema: Record<string, unknown>
): unknown {
  const defaultValue = getSchemaDefault(propSchema);
  if (defaultValue !== undefined) return defaultValue;
  const enumValues = getSchemaEnumValues(propSchema);
  if (enumValues.length > 0) return enumValues[0];
  switch (getSchemaType(propSchema)) {
    case 'string':
      return '';
    case 'number':
    case 'integer':
      return 0;
    case 'boolean':
      return false;
    case 'array':
      return [];
    case 'object':
      return {};
    default:
      return null;
  }
}

function buildDefaultConfig(configSchema: unknown): Record<string, unknown> {
  const schema = asSchema(configSchema);
  if (!schema) return {};
  const normalized = normalizeSchema(schema, schema);
  if (!normalized) return {};
  const properties = getSchemaProperties(normalized);
  const required = new Set(getSchemaRequiredProperties(normalized));
  const config: Record<string, unknown> = {};
  for (const [name, raw] of Object.entries(properties)) {
    const propSchema = normalizeSchema(raw, schema);
    if (!propSchema) continue;
    const explicitDefault = getSchemaDefault(propSchema);
    if (required.has(name) || explicitDefault !== undefined) {
      config[name] = getDefaultValueForSchema(propSchema);
    }
  }
  return config;
}

function findEvaluatorConfigEdit(
  text: string,
  previousNames: Map<string, string>,
  evaluators: JsonEditorEvaluatorOption[] | undefined
): JsonEditorTextEdit | null {
  const tree = parseTree(text);
  if (!tree) return null;
  const conditionNode = findNodeAtLocation(tree, ['condition']);
  const result = new Map<string, EvaluatorNodeInfo>();
  collectEvaluatorNames(conditionNode, result);

  for (const [key, { name, configNode, nameNode }] of result) {
    const prevName = previousNames.get(key);
    if (prevName === undefined || prevName === name) continue;
    const evaluator = evaluators?.find((item) => item.id === name);
    if (!evaluator) continue;
    const configJson = JSON.stringify(
      buildDefaultConfig(evaluator.configSchema),
      null,
      2
    );
    if (configNode) {
      return {
        offset: configNode.offset,
        length: configNode.length,
        newText: configJson,
      };
    }
    const nameEnd = nameNode.offset + nameNode.length;
    return {
      offset: nameEnd,
      length: 0,
      newText: `,\n"config": ${configJson}`,
    };
  }
  return null;
}

function findSteeringContextEdit(
  text: string,
  previousDecision: string | null
): JsonEditorTextEdit | null {
  const tree = parseTree(text);
  if (!tree) return null;
  const decisionNode = findNodeAtLocation(tree, ['action', 'decision']);
  if (!decisionNode || typeof decisionNode.value !== 'string') return null;

  const currentDecision = decisionNode.value;
  if (currentDecision === previousDecision) return null;

  if (currentDecision === 'steer') {
    const steeringNode = findNodeAtLocation(tree, [
      'action',
      'steering_context',
    ]);
    if (!steeringNode) {
      const decisionEnd = decisionNode.offset + decisionNode.length;
      return {
        offset: decisionEnd,
        length: 0,
        newText: `,\n"steering_context": {"message": "Please correct your response."}`,
      };
    }
  } else if (previousDecision === 'steer') {
    const actionNode = findNodeAtLocation(tree, ['action']);
    if (actionNode?.type === 'object' && actionNode.children) {
      for (const prop of actionNode.children) {
        const key = prop.children?.[0];
        if (key?.value === 'steering_context') {
          let start = prop.offset;
          while (start > 0 && /[\s,]/.test(text[start - 1] ?? '')) start -= 1;
          return {
            offset: start,
            length: prop.offset + prop.length - start,
            newText: '',
          };
        }
      }
    }
  }
  return null;
}

export function computeAutoEdit(
  text: string,
  previousEvaluatorNames: Map<string, string>,
  previousDecision: string | null,
  mode: JsonEditorMode,
  evaluators: JsonEditorEvaluatorOption[] | undefined
): {
  edit: JsonEditorTextEdit | null;
  editKind: 'evaluator-config' | 'steering-context' | null;
  nextEvaluatorNames: Map<string, string>;
  nextDecision: string | null;
} {
  const nextEvaluatorNames = extractEvaluatorNames(text);
  let nextDecision: string | null = previousDecision;
  try {
    const tree = parseTree(text);
    if (tree) {
      const node = findNodeAtLocation(tree, ['action', 'decision']);
      nextDecision = typeof node?.value === 'string' ? node.value : null;
    }
  } catch {
    nextDecision = previousDecision;
  }

  if (mode !== 'control') {
    return { edit: null, editKind: null, nextEvaluatorNames, nextDecision };
  }

  const evaluatorEdit = findEvaluatorConfigEdit(
    text,
    previousEvaluatorNames,
    evaluators
  );
  if (evaluatorEdit) {
    return {
      edit: evaluatorEdit,
      editKind: 'evaluator-config',
      nextEvaluatorNames,
      nextDecision,
    };
  }

  const steeringEdit = findSteeringContextEdit(text, previousDecision);
  if (steeringEdit) {
    return {
      edit: steeringEdit,
      editKind: 'steering-context',
      nextEvaluatorNames,
      nextDecision,
    };
  }

  return { edit: null, editKind: null, nextEvaluatorNames, nextDecision };
}

export function applyTextEdit(text: string, edit: JsonEditorTextEdit): string {
  return (
    text.slice(0, edit.offset) +
    edit.newText +
    text.slice(edit.offset + edit.length)
  );
}
