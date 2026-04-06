import {
  findNodeAtLocation,
  type Node as JsonNode,
  parseTree,
} from 'jsonc-parser';

import type { JsonEditorEvaluatorOption } from '@/core/page-components/agent-detail/modals/edit-control/types';

import {
  asSchema,
  getSchemaAtProperty,
  getSchemaEnumValues,
  normalizeSchema,
} from './schema';
import type {
  JsonEditorCodeMirrorContext,
  JsonPath,
  SchemaCursor,
} from './types';

export function isEvaluatorNameLocation(path: JsonPath): boolean {
  return (
    path.length >= 2 &&
    path[path.length - 1] === 'name' &&
    path[path.length - 2] === 'evaluator'
  );
}

export function isSelectorPathLocation(path: JsonPath): boolean {
  return (
    path.length >= 2 &&
    path[path.length - 1] === 'path' &&
    path[path.length - 2] === 'selector'
  );
}

export function getStringArrayAtPath(
  tree: JsonNode | undefined,
  path: JsonPath
): string[] {
  const node = tree ? findNodeAtLocation(tree, path) : undefined;
  if (!node || node.type !== 'array' || !node.children) return [];
  return node.children
    .map((child) => (typeof child.value === 'string' ? child.value : null))
    .filter((value): value is string => value !== null);
}

export function getScopeFilters(tree: JsonNode | undefined): {
  stepTypes: string[];
  stepNames: string[];
} {
  return {
    stepTypes: getStringArrayAtPath(tree, ['scope', 'step_types']),
    stepNames: getStringArrayAtPath(tree, ['scope', 'step_names']),
  };
}

export function resolveActiveEvaluator(
  context: JsonEditorCodeMirrorContext,
  tree: JsonNode | undefined,
  path: JsonPath
): JsonEditorEvaluatorOption | null {
  if (context.mode === 'evaluator-config') {
    return (
      context.evaluators?.find(
        (item) => item.id === context.activeEvaluatorId
      ) ?? null
    );
  }

  const evaluatorIndex = path.lastIndexOf('evaluator');
  if (evaluatorIndex === -1 || !tree) return null;
  const evaluatorPath = path.slice(0, evaluatorIndex + 1);
  const nameNode = findNodeAtLocation(tree, [...evaluatorPath, 'name']);
  const value = typeof nameNode?.value === 'string' ? nameNode.value : null;
  if (!value) return null;
  return context.evaluators?.find((item) => item.id === value) ?? null;
}

/**
 * True when `path[index]` is the `config` property of an `evaluator` object.
 * Matches Monaco `isEvaluatorConfigSegment` — used to swap the schema root to
 * the active evaluator's configSchema while editing control JSON.
 */
function isEvaluatorConfigSegment(path: JsonPath, index: number): boolean {
  return (
    typeof path[index] === 'string' &&
    path[index] === 'config' &&
    index > 0 &&
    path[index - 1] === 'evaluator'
  );
}

export function resolveSchemaAtJsonPath(
  context: JsonEditorCodeMirrorContext,
  activeEvaluator: JsonEditorEvaluatorOption | null,
  path: JsonPath
): SchemaCursor {
  const controlRoot = asSchema(context.schema) ?? null;
  let rootSchema = controlRoot;
  if (context.mode === 'evaluator-config' && activeEvaluator?.configSchema) {
    rootSchema = asSchema(activeEvaluator.configSchema) ?? rootSchema;
  }
  if (!rootSchema) return { schema: null, rootSchema: null };

  let cursor = normalizeSchema(rootSchema, rootSchema);

  for (let index = 0; index < path.length; index += 1) {
    const segment = path[index];
    if (cursor === null) break;

    if (context.mode === 'control' && isEvaluatorConfigSegment(path, index)) {
      const configRoot = asSchema(activeEvaluator?.configSchema ?? null);
      if (configRoot) {
        rootSchema = configRoot;
        cursor = normalizeSchema(rootSchema, rootSchema);
        continue;
      }
    }

    if (typeof segment === 'number') {
      const normalized = normalizeSchema(cursor, rootSchema);
      cursor = normalizeSchema(normalized?.items, rootSchema);
      continue;
    }
    cursor = getSchemaAtProperty(cursor, segment, rootSchema);
  }
  return { schema: cursor, rootSchema };
}

export function getSchemaDescription(
  schema: Record<string, unknown> | null
): string | null {
  return typeof schema?.description === 'string' ? schema.description : null;
}

export function getSchemaTitle(
  schema: Record<string, unknown> | null
): string | null {
  return typeof schema?.title === 'string' ? schema.title : null;
}

export function parseJsonTree(text: string): JsonNode | undefined {
  return parseTree(text) ?? undefined;
}

export function getEnumValues(
  schema: Record<string, unknown> | null
): unknown[] {
  return getSchemaEnumValues(schema);
}
