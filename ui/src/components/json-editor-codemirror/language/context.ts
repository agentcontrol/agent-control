import {
  findNodeAtLocation,
  type Node as JsonNode,
  parseTree,
} from 'jsonc-parser';

import type { JsonEditorRuleOption } from '@/core/page-components/agent-detail/modals/edit-control/types';

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

export function isRuleNameLocation(path: JsonPath): boolean {
  return (
    path.length >= 2 &&
    path[path.length - 1] === 'name' &&
    path[path.length - 2] === 'rule'
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

export function resolveActiveRule(
  context: JsonEditorCodeMirrorContext,
  tree: JsonNode | undefined,
  path: JsonPath
): JsonEditorRuleOption | null {
  if (context.mode === 'rule-config') {
    return (
      context.rules?.find((item) => item.id === context.activeRuleId) ?? null
    );
  }

  const ruleIndex = path.lastIndexOf('rule');
  if (ruleIndex === -1 || !tree) return null;
  const rulePath = path.slice(0, ruleIndex + 1);
  const nameNode = findNodeAtLocation(tree, [...rulePath, 'name']);
  const value = typeof nameNode?.value === 'string' ? nameNode.value : null;
  if (!value) return null;
  return context.rules?.find((item) => item.id === value) ?? null;
}

/**
 * True when `path[index]` is the `config` property of an `rule` object.
 * Matches Monaco `isRuleConfigSegment` — used to swap the schema root to
 * the active rule's configSchema while editing control JSON.
 */
function isRuleConfigSegment(path: JsonPath, index: number): boolean {
  return (
    typeof path[index] === 'string' &&
    path[index] === 'config' &&
    index > 0 &&
    path[index - 1] === 'rule'
  );
}

export function resolveSchemaAtJsonPath(
  context: JsonEditorCodeMirrorContext,
  activeRule: JsonEditorRuleOption | null,
  path: JsonPath
): SchemaCursor {
  const controlRoot = asSchema(context.schema) ?? null;
  let rootSchema = controlRoot;
  if (context.mode === 'rule-config' && activeRule?.configSchema) {
    rootSchema = asSchema(activeRule.configSchema) ?? rootSchema;
  }
  if (!rootSchema) return { schema: null, rootSchema: null };

  let cursor = normalizeSchema(rootSchema, rootSchema);

  for (let index = 0; index < path.length; index += 1) {
    const segment = path[index];
    if (cursor === null) break;

    if (context.mode === 'control' && isRuleConfigSegment(path, index)) {
      const configRoot = asSchema(activeRule?.configSchema ?? null);
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
