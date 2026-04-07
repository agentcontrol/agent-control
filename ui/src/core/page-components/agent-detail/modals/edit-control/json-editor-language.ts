import {
  findNodeAtLocation,
  findNodeAtOffset,
  getLocation,
  type Node as JsonNode,
  type ParseError,
  parseTree,
} from 'jsonc-parser';

import type { StepSchema } from '@/core/api/types';

import type {
  JsonEditorEvaluatorOption,
  JsonEditorMode,
  JsonSchema,
} from './types';

type MonacoModule = typeof import('monaco-editor');
type JsonPath = Array<string | number>;

type JsonEditorAutocompleteContext = {
  mode: JsonEditorMode;
  modelUri: string;
  schema?: JsonSchema | null;
  evaluators?: JsonEditorEvaluatorOption[];
  activeEvaluatorId?: string | null;
  steps?: StepSchema[];
};

type SelectorPathSuggestion = {
  label: string;
  detail: string;
  rank: number;
};

type SchemaCursor = {
  schema: JsonSchema | null;
  rootSchema: JsonSchema | null;
};

type SnippetState = {
  nextTabStop: number;
};

const ROOT_SELECTOR_PATHS = ['*', 'input', 'output', 'context', 'name', 'type'];
const COMPLETION_TRIGGER_CHARACTERS = ['"', ':', '.', ',', '['];
const SCHEMA_COMPOSITION_KEYS = ['$ref', 'allOf', 'anyOf', 'oneOf'];
const RESERVED_SCHEMA_KEYS = new Set([
  ...SCHEMA_COMPOSITION_KEYS,
  '$defs',
  'additionalProperties',
  'default',
  'description',
  'enum',
  'examples',
  'items',
  'properties',
  'required',
  'title',
  'type',
]);

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function asSchema(schema: unknown): JsonSchema | null {
  return isObject(schema) ? schema : null;
}

function getStringArrayAtPath(
  tree: JsonNode | undefined,
  path: JsonPath
): string[] {
  const node = tree ? findNodeAtLocation(tree, path) : undefined;
  if (!node || node.type !== 'array' || !node.children) {
    return [];
  }

  return node.children
    .map((child) => (typeof child.value === 'string' ? child.value : null))
    .filter((value): value is string => value !== null);
}

function getScopeFilters(tree: JsonNode | undefined): {
  stepTypes: string[];
  stepNames: string[];
} {
  return {
    stepTypes: getStringArrayAtPath(tree, ['scope', 'step_types']),
    stepNames: getStringArrayAtPath(tree, ['scope', 'step_names']),
  };
}

function getJsonPathFieldIndex(path: JsonPath, fieldName: string): number {
  for (let index = path.length - 1; index >= 0; index -= 1) {
    if (path[index] === fieldName) {
      return index;
    }
  }
  return -1;
}

function getRangeForNodeContent(
  monaco: MonacoModule,
  model: import('monaco-editor').editor.ITextModel,
  node: JsonNode | undefined
) {
  if (!node || node.type !== 'string') {
    return null;
  }

  const start = model.getPositionAt(node.offset + 1);
  const end = model.getPositionAt(node.offset + Math.max(node.length - 1, 1));

  return new monaco.Range(
    start.lineNumber,
    start.column,
    end.lineNumber,
    end.column
  );
}

function getDefaultRange(
  monaco: MonacoModule,
  model: import('monaco-editor').editor.ITextModel,
  position: import('monaco-editor').Position
) {
  const word = model.getWordUntilPosition(position);

  return new monaco.Range(
    position.lineNumber,
    word.startColumn,
    position.lineNumber,
    word.endColumn
  );
}

function getReplaceRange(
  monaco: MonacoModule,
  model: import('monaco-editor').editor.ITextModel,
  position: import('monaco-editor').Position,
  node: JsonNode | undefined
) {
  return (
    getRangeForNodeContent(monaco, model, node) ??
    getDefaultRange(monaco, model, position)
  );
}

function getPropertyKeyReplaceRange(
  monaco: MonacoModule,
  model: import('monaco-editor').editor.ITextModel,
  node: JsonNode | undefined
) {
  if (!node || node.type !== 'string') {
    return null;
  }

  const start = model.getPositionAt(node.offset + 1);
  const end = model.getPositionAt(node.offset + node.length);

  return new monaco.Range(
    start.lineNumber,
    start.column,
    end.lineNumber,
    end.column
  );
}

function unescapeJsonPointerSegment(segment: string): string {
  return segment.replace(/~1/g, '/').replace(/~0/g, '~');
}

function resolveJsonPointer(
  rootSchema: JsonSchema | null,
  ref: string
): JsonSchema | null {
  if (!rootSchema || !ref.startsWith('#/')) {
    return null;
  }

  let current: unknown = rootSchema;
  for (const segment of ref
    .slice(2)
    .split('/')
    .map(unescapeJsonPointerSegment)) {
    if (!isObject(current) || !(segment in current)) {
      return null;
    }
    current = current[segment];
  }

  return asSchema(current);
}

function getSchemaTypes(schema: unknown): string[] {
  if (!isObject(schema)) {
    return [];
  }

  if (typeof schema.type === 'string') {
    return [schema.type];
  }

  if (!Array.isArray(schema.type)) {
    return [];
  }

  return schema.type.filter(
    (value): value is string => typeof value === 'string'
  );
}

function getSchemaType(schema: unknown): string | null {
  return getSchemaTypes(schema).find((value) => value !== 'null') ?? null;
}

function getSchemaEnumValues(schema: unknown): unknown[] {
  return isObject(schema) && Array.isArray(schema.enum) ? schema.enum : [];
}

function stripCompositionKeys(schema: JsonSchema): JsonSchema {
  const stripped = { ...schema };
  for (const key of SCHEMA_COMPOSITION_KEYS) {
    delete stripped[key];
  }
  return stripped;
}

function mergeSchemas(
  schemas: JsonSchema[],
  baseSchema?: JsonSchema | null
): JsonSchema {
  const merged: JsonSchema = baseSchema ? stripCompositionKeys(baseSchema) : {};
  const properties: Record<string, unknown> = {};
  const required = new Set<string>();
  const enumValues: unknown[] = [];
  const types = new Set<string>();
  let items: unknown;
  let additionalProperties: unknown;

  for (const schema of schemas) {
    for (const type of getSchemaTypes(schema)) {
      if (type !== 'null') {
        types.add(type);
      }
    }

    for (const value of getSchemaEnumValues(schema)) {
      if (!enumValues.some((candidate) => candidate === value)) {
        enumValues.push(value);
      }
    }

    if (isObject(schema.properties)) {
      Object.assign(properties, schema.properties);
    }

    if (Array.isArray(schema.required)) {
      for (const value of schema.required) {
        if (typeof value === 'string') {
          required.add(value);
        }
      }
    }

    if (items === undefined && schema.items !== undefined) {
      items = schema.items;
    }

    if (
      additionalProperties === undefined &&
      schema.additionalProperties !== undefined
    ) {
      additionalProperties = schema.additionalProperties;
    }

    if (
      merged.description === undefined &&
      typeof schema.description === 'string'
    ) {
      merged.description = schema.description;
    }

    if (merged.title === undefined && typeof schema.title === 'string') {
      merged.title = schema.title;
    }

    if (merged.default === undefined && 'default' in schema) {
      merged.default = schema.default;
    }

    if (
      merged.examples === undefined &&
      Array.isArray(schema.examples) &&
      schema.examples.length > 0
    ) {
      merged.examples = schema.examples;
    }
  }

  if (Object.keys(properties).length > 0) {
    merged.properties = properties;
  }

  if (required.size > 0) {
    merged.required = [...required];
  }

  if (enumValues.length > 0) {
    merged.enum = enumValues;
  }

  if (types.size === 1) {
    merged.type = [...types][0];
  } else if (types.size > 1) {
    merged.type = [...types];
  }

  if (items !== undefined) {
    merged.items = items;
  }

  if (additionalProperties !== undefined) {
    merged.additionalProperties = additionalProperties;
  }

  return merged;
}

function normalizeSchema(
  schema: unknown,
  rootSchema: JsonSchema | null,
  seenRefs: Set<string> = new Set()
): JsonSchema | null {
  const current = asSchema(schema);
  if (!current) {
    return null;
  }

  if (typeof current.$ref === 'string') {
    const ref = current.$ref;
    if (seenRefs.has(ref)) {
      return stripCompositionKeys(current);
    }

    const resolved = resolveJsonPointer(rootSchema, ref);
    if (!resolved) {
      return stripCompositionKeys(current);
    }

    const localOverrides = stripCompositionKeys(current);
    const nextSeenRefs = new Set(seenRefs);
    nextSeenRefs.add(ref);
    const normalizedResolved = normalizeSchema(
      resolved,
      rootSchema,
      nextSeenRefs
    );
    return normalizedResolved
      ? mergeSchemas([normalizedResolved, localOverrides])
      : localOverrides;
  }

  if (Array.isArray(current.allOf) && current.allOf.length > 0) {
    const variants = current.allOf
      .map((variant) => normalizeSchema(variant, rootSchema, seenRefs))
      .filter((variant): variant is JsonSchema => variant !== null);

    if (variants.length > 0) {
      return mergeSchemas(variants, current);
    }
  }

  const union = Array.isArray(current.anyOf)
    ? current.anyOf
    : Array.isArray(current.oneOf)
      ? current.oneOf
      : null;

  if (union && union.length > 0) {
    const variants = union
      .map((variant) => normalizeSchema(variant, rootSchema, seenRefs))
      .filter((variant): variant is JsonSchema => variant !== null);

    const nonNullVariants = variants.filter(
      (variant) => getSchemaType(variant) !== 'null'
    );

    if (nonNullVariants.length > 0) {
      return mergeSchemas(nonNullVariants, current);
    }
  }

  return current;
}

function getSchemaProperties(schema: unknown): Record<string, unknown> {
  const normalized = normalizeSchema(schema, asSchema(schema));
  if (!normalized) {
    return {};
  }

  if (isObject(normalized.properties)) {
    return normalized.properties;
  }

  const propertyEntries = Object.entries(normalized).filter(
    ([key, value]) => !RESERVED_SCHEMA_KEYS.has(key) && isObject(value)
  );

  return Object.fromEntries(propertyEntries);
}

function getSchemaRequiredProperties(schema: unknown): string[] {
  if (!isObject(schema) || !Array.isArray(schema.required)) {
    return [];
  }

  return schema.required.filter(
    (value): value is string => typeof value === 'string'
  );
}

function getSchemaAtProperty(
  schema: JsonSchema | null,
  propertyName: string,
  rootSchema: JsonSchema | null
): JsonSchema | null {
  const normalized = normalizeSchema(schema, rootSchema);
  if (!normalized) {
    return null;
  }

  const properties = getSchemaProperties(normalized);
  if (propertyName in properties) {
    return normalizeSchema(properties[propertyName], rootSchema);
  }

  if (isObject(normalized.additionalProperties)) {
    return normalizeSchema(normalized.additionalProperties, rootSchema);
  }

  return null;
}

function getArrayItemSchema(
  schema: JsonSchema | null,
  rootSchema: JsonSchema | null
): JsonSchema | null {
  const normalized = normalizeSchema(schema, rootSchema);
  if (!normalized) {
    return null;
  }

  return normalizeSchema(normalized.items, rootSchema);
}

function getPropertyKeyContext(
  path: JsonPath,
  isAtPropertyKey: boolean
): { objectPath: JsonPath; replaceExistingKey: boolean } | null {
  if (!isAtPropertyKey || path.length === 0) {
    return null;
  }

  const last = path[path.length - 1];
  if (last === '') {
    return { objectPath: path.slice(0, -1), replaceExistingKey: false };
  }

  if (typeof last === 'string') {
    return { objectPath: path.slice(0, -1), replaceExistingKey: true };
  }

  return null;
}

function isSelectorPathLocation(path: JsonPath): boolean {
  return (
    path.length >= 2 &&
    path[path.length - 1] === 'path' &&
    path[path.length - 2] === 'selector'
  );
}

function isEvaluatorNameLocation(path: JsonPath): boolean {
  return (
    path.length >= 2 &&
    path[path.length - 1] === 'name' &&
    path[path.length - 2] === 'evaluator'
  );
}

function escapeSnippetValue(value: string): string {
  return value.replace(/[\\$}]/g, '\\$&');
}

function toJsonLiteral(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function getSchemaDescription(schema: unknown): string | undefined {
  return isObject(schema) && typeof schema.description === 'string'
    ? schema.description
    : undefined;
}

function getSchemaTitle(schema: unknown): string | undefined {
  return isObject(schema) && typeof schema.title === 'string'
    ? schema.title
    : undefined;
}

function isSchemaWithProperties(
  schema: JsonSchema,
  propertyNames: string[]
): boolean {
  const properties = getSchemaProperties(schema);
  return propertyNames.every((propertyName) => propertyName in properties);
}

function getSchemaExamples(schema: unknown): unknown[] {
  return isObject(schema) && Array.isArray(schema.examples)
    ? schema.examples
    : [];
}

function getSchemaDefault(schema: unknown): unknown {
  return isObject(schema) && 'default' in schema ? schema.default : undefined;
}

function nextSnippetTabStop(
  snippetState: SnippetState,
  defaultValue?: string
): string {
  const tabStop = snippetState.nextTabStop;
  snippetState.nextTabStop += 1;

  if (defaultValue) {
    return `\${${tabStop}:${escapeSnippetValue(defaultValue)}}`;
  }

  return `\${${tabStop}}`;
}

function getSuggestedObjectPropertyNames(schema: JsonSchema): string[] {
  const properties = Object.keys(getSchemaProperties(schema));
  if (properties.length === 0) {
    return [];
  }

  const required = getSchemaRequiredProperties(schema);
  if (required.length > 0) {
    return required.filter((propertyName) => properties.includes(propertyName));
  }

  if (properties.length === 1) {
    return properties;
  }

  return [];
}

function buildSchemaValueSnippet(
  schema: JsonSchema | null,
  rootSchema: JsonSchema | null,
  snippetState: SnippetState,
  depth = 0
): string {
  const normalized = normalizeSchema(schema, rootSchema);
  if (!normalized || depth > 4) {
    return nextSnippetTabStop(snippetState);
  }

  const enumValues = getSchemaEnumValues(normalized);
  if (enumValues.length > 0) {
    return toJsonLiteral(enumValues[0]);
  }

  const examples = getSchemaExamples(normalized);
  const defaultValue = getSchemaDefault(normalized);
  const preferredValue =
    defaultValue !== undefined ? defaultValue : examples[0];
  const schemaTitle = getSchemaTitle(normalized);

  if (
    schemaTitle === 'ControlSelector' ||
    isSchemaWithProperties(normalized, ['path'])
  ) {
    return '{\n  "path": "*"\n}';
  }

  if (
    schemaTitle === 'EvaluatorSpec' ||
    isSchemaWithProperties(normalized, ['name', 'config'])
  ) {
    return '{\n  "name": "",\n  "config": {}\n}';
  }

  if (
    schemaTitle === 'ControlAction' ||
    isSchemaWithProperties(normalized, ['decision', 'steering_context'])
  ) {
    return '{\n  "decision": "deny"\n}';
  }

  if (
    schemaTitle === 'ControlScope' ||
    isSchemaWithProperties(normalized, ['step_types', 'stages'])
  ) {
    return '{\n  "step_types": ["llm"],\n  "stages": ["post"]\n}';
  }

  if (
    schemaTitle === 'ConditionNode' ||
    isSchemaWithProperties(normalized, [
      'selector',
      'evaluator',
      'and',
      'or',
      'not',
    ])
  ) {
    return '{}';
  }

  switch (getSchemaType(normalized)) {
    case 'object': {
      return '{}';
    }
    case 'array': {
      return '[]';
    }
    case 'boolean': {
      return String(
        typeof preferredValue === 'boolean' ? preferredValue : true
      );
    }
    case 'integer':
    case 'number': {
      return String(typeof preferredValue === 'number' ? preferredValue : 0);
    }
    case 'string': {
      if (typeof preferredValue === 'string' && preferredValue.length > 0) {
        return `"${escapeSnippetValue(preferredValue)}"`;
      }
      return `"${nextSnippetTabStop(snippetState)}"`;
    }
    default: {
      if (preferredValue !== undefined) {
        return toJsonLiteral(preferredValue);
      }
      return 'null';
    }
  }
}

function buildPropertyInsertText(
  propertyName: string,
  propertySchema: JsonSchema | null,
  rootSchema: JsonSchema | null,
  replaceExistingKey = false
): string {
  const snippetState: SnippetState = { nextTabStop: 1 };
  const valueSnippet = buildSchemaValueSnippet(
    propertySchema,
    rootSchema,
    snippetState
  );
  const prefix = replaceExistingKey
    ? `${escapeSnippetValue(propertyName)}": `
    : `"${escapeSnippetValue(propertyName)}": `;
  return `${prefix}${valueSnippet}`;
}

function buildValueInsertText(
  value: unknown,
  isStringValueContext: boolean
): string {
  return typeof value === 'string' && isStringValueContext
    ? value
    : toJsonLiteral(value);
}

function getObjectPropertyNames(node: JsonNode | undefined): Set<string> {
  if (!node || node.type !== 'object' || !node.children) {
    return new Set();
  }

  return new Set(
    node.children
      .map((propertyNode) => {
        const keyNode = propertyNode.children?.[0];
        return typeof keyNode?.value === 'string' ? keyNode.value : null;
      })
      .filter((value): value is string => value !== null)
  );
}

function getExistingKeysFromText(text: string, offset: number): Set<string> {
  let braceDepth = 0;
  let objectStart = -1;
  for (let i = offset - 1; i >= 0; i -= 1) {
    if (text[i] === '}') braceDepth += 1;
    if (text[i] === '{') {
      if (braceDepth === 0) {
        objectStart = i;
        break;
      }
      braceDepth -= 1;
    }
  }
  if (objectStart < 0) return new Set();

  braceDepth = 0;
  let objectEnd = text.length;
  for (let i = objectStart; i < text.length; i += 1) {
    if (text[i] === '{') braceDepth += 1;
    if (text[i] === '}') {
      braceDepth -= 1;
      if (braceDepth === 0) {
        objectEnd = i;
        break;
      }
    }
  }

  const keys = new Set<string>();
  const pattern = /"([^"]+)"\s*:/g;
  let match;
  const slice = text.substring(objectStart, objectEnd + 1);
  while ((match = pattern.exec(slice)) !== null) {
    keys.add(match[1]);
  }
  return keys;
}

function walkSchemaPaths(
  schema: unknown,
  basePath: string,
  output: Set<string>,
  depth = 0
) {
  if (depth > 5) {
    return;
  }

  output.add(basePath);
  const properties = getSchemaProperties(schema);
  for (const [propertyName, propertySchema] of Object.entries(properties)) {
    const childPath = `${basePath}.${propertyName}`;
    output.add(childPath);
    walkSchemaPaths(propertySchema, childPath, output, depth + 1);
  }
}

function buildSelectorPathSuggestions(
  steps: StepSchema[] | undefined,
  tree: JsonNode | undefined
): SelectorPathSuggestion[] {
  const suggestions = new Map<string, SelectorPathSuggestion>();
  const { stepTypes, stepNames } = getScopeFilters(tree);
  const rankedSteps = steps ?? [];

  for (const rootPath of ROOT_SELECTOR_PATHS) {
    suggestions.set(rootPath, {
      label: rootPath,
      detail: 'Built-in control selector root',
      rank: 0,
    });
  }

  const getStepRank = (step: StepSchema): number => {
    const typeMatches = stepTypes.length === 0 || stepTypes.includes(step.type);
    const nameMatches = stepNames.length === 0 || stepNames.includes(step.name);

    if (typeMatches && nameMatches) return 0;
    if (typeMatches || nameMatches) return 1;
    return 2;
  };

  for (const step of rankedSteps) {
    const rank = getStepRank(step);
    const stepLabel = `${step.type}:${step.name}`;
    const inputPaths = new Set<string>(['input']);
    const outputPaths = new Set<string>(['output']);

    if (step.input_schema) {
      walkSchemaPaths(step.input_schema, 'input', inputPaths);
    }

    if (step.output_schema) {
      walkSchemaPaths(step.output_schema, 'output', outputPaths);
    }

    for (const path of [...inputPaths, ...outputPaths]) {
      const existing = suggestions.get(path);
      if (!existing || rank < existing.rank) {
        suggestions.set(path, {
          label: path,
          detail: stepLabel,
          rank,
        });
      }
    }
  }

  return [...suggestions.values()].sort((left, right) => {
    if (left.rank !== right.rank) {
      return left.rank - right.rank;
    }
    return left.label.localeCompare(right.label);
  });
}

function findEvaluatorById(
  evaluators: JsonEditorEvaluatorOption[] | undefined,
  id: string | null | undefined
): JsonEditorEvaluatorOption | null {
  if (!evaluators || !id) {
    return null;
  }

  return evaluators.find((candidate) => candidate.id === id) ?? null;
}

function resolveActiveEvaluator(
  context: JsonEditorAutocompleteContext,
  tree: JsonNode | undefined,
  path: JsonPath
): JsonEditorEvaluatorOption | null {
  if (context.mode === 'evaluator-config') {
    return findEvaluatorById(context.evaluators, context.activeEvaluatorId);
  }

  const evaluatorIndex = getJsonPathFieldIndex(path, 'evaluator');
  if (!tree || evaluatorIndex < 0) {
    return null;
  }

  const evaluatorNamePath = [
    ...path.slice(0, evaluatorIndex),
    'evaluator',
    'name',
  ];
  const evaluatorNameNode = findNodeAtLocation(tree, evaluatorNamePath);
  const evaluatorName =
    typeof evaluatorNameNode?.value === 'string'
      ? evaluatorNameNode.value
      : null;

  return findEvaluatorById(context.evaluators, evaluatorName);
}

function getInitialSchemaCursor(
  context: JsonEditorAutocompleteContext,
  activeEvaluator: JsonEditorEvaluatorOption | null
): SchemaCursor {
  if (context.mode === 'evaluator-config') {
    const rootSchema = asSchema(activeEvaluator?.configSchema ?? null);
    return {
      schema: normalizeSchema(rootSchema, rootSchema),
      rootSchema,
    };
  }

  const rootSchema = asSchema(context.schema ?? null);
  return {
    schema: normalizeSchema(rootSchema, rootSchema),
    rootSchema,
  };
}

function isEvaluatorConfigSegment(path: JsonPath, index: number): boolean {
  return (
    typeof path[index] === 'string' &&
    path[index] === 'config' &&
    index > 0 &&
    path[index - 1] === 'evaluator'
  );
}

function resolveSchemaAtJsonPath(
  context: JsonEditorAutocompleteContext,
  activeEvaluator: JsonEditorEvaluatorOption | null,
  path: JsonPath
): SchemaCursor {
  let cursor = getInitialSchemaCursor(context, activeEvaluator);

  for (let index = 0; index < path.length; index += 1) {
    const segment = path[index];
    if (!cursor.schema) {
      return cursor;
    }

    if (context.mode === 'control' && isEvaluatorConfigSegment(path, index)) {
      const rootSchema = asSchema(activeEvaluator?.configSchema ?? null);
      cursor = {
        schema: normalizeSchema(rootSchema, rootSchema),
        rootSchema,
      };
      continue;
    }

    if (typeof segment === 'number') {
      cursor = {
        schema: getArrayItemSchema(cursor.schema, cursor.rootSchema),
        rootSchema: cursor.rootSchema,
      };
      continue;
    }

    cursor = {
      schema: getSchemaAtProperty(cursor.schema, segment, cursor.rootSchema),
      rootSchema: cursor.rootSchema,
    };
  }

  return cursor;
}

function buildEvaluatorNameSuggestions(
  monaco: MonacoModule,
  range: import('monaco-editor').IRange,
  evaluators: JsonEditorEvaluatorOption[] | undefined,
  isStringValueContext: boolean
) {
  return (evaluators ?? []).map((evaluator, index) => ({
    label: evaluator.id,
    kind: monaco.languages.CompletionItemKind.Value,
    detail:
      evaluator.source === 'agent'
        ? `${evaluator.label} (agent evaluator)`
        : evaluator.label,
    documentation: evaluator.description ?? undefined,
    insertText: buildValueInsertText(evaluator.id, isStringValueContext),
    range,
    sortText: `!0${index.toString().padStart(3, '0')}`,
  }));
}

function buildSelectorSuggestions(
  monaco: MonacoModule,
  range: import('monaco-editor').IRange,
  steps: StepSchema[] | undefined,
  tree: JsonNode | undefined,
  isStringValueContext: boolean
) {
  return buildSelectorPathSuggestions(steps, tree).map((suggestion, index) => ({
    label: suggestion.label,
    kind: monaco.languages.CompletionItemKind.Value,
    detail: suggestion.detail,
    insertText: buildValueInsertText(suggestion.label, isStringValueContext),
    range,
    sortText: `!${suggestion.rank}${index.toString().padStart(3, '0')}`,
  }));
}

function buildSchemaPropertySuggestions(
  monaco: MonacoModule,
  range: import('monaco-editor').IRange,
  schemaCursor: SchemaCursor,
  tree: JsonNode | undefined,
  objectPath: JsonPath,
  replaceExistingKey: boolean,
  currentPropertyName: string | null,
  text: string,
  offset: number
) {
  if (!schemaCursor.schema) {
    return [];
  }

  const objectNode = tree ? findNodeAtLocation(tree, objectPath) : undefined;
  // Use AST-based key detection, with text-based fallback for broken JSON
  const existingKeys = objectNode
    ? getObjectPropertyNames(objectNode)
    : getExistingKeysFromText(text, offset);
  if (currentPropertyName) {
    existingKeys.delete(currentPropertyName);
  }

  return Object.entries(getSchemaProperties(schemaCursor.schema))
    .filter(
      ([propertyName]) =>
        !existingKeys.has(propertyName) && !propertyName.startsWith('$')
    )
    .map(([propertyName, propertySchema], index) => ({
      label: propertyName,
      kind: monaco.languages.CompletionItemKind.Property,
      detail: getSchemaDescription(propertySchema),
      documentation: getSchemaDescription(propertySchema),
      insertText: buildPropertyInsertText(
        propertyName,
        asSchema(propertySchema),
        schemaCursor.rootSchema,
        replaceExistingKey
      ),
      insertTextRules:
        monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
      range,
      sortText: `!1${index.toString().padStart(3, '0')}`,
    }));
}

function buildSchemaValueSuggestions(
  monaco: MonacoModule,
  range: import('monaco-editor').IRange,
  schemaCursor: SchemaCursor,
  isStringValueContext: boolean,
  currentValue?: string
) {
  const schema = schemaCursor.schema;
  if (!schema) {
    return [];
  }

  const suggestions: import('monaco-editor').languages.CompletionItem[] = [];
  const enumValues = getSchemaEnumValues(schema);

  if (enumValues.length > 0) {
    suggestions.push(
      ...enumValues.map((value, index) => ({
        label: String(value),
        kind: monaco.languages.CompletionItemKind.Value,
        detail: getSchemaTitle(schema) ?? getSchemaDescription(schema),
        insertText: buildValueInsertText(value, isStringValueContext),
        // Show all enum options regardless of the current value. Monaco
        // fuzzy-matches text between range start and cursor, so setting
        // filterText to the current string value makes every item pass.
        filterText: currentValue ?? undefined,
        range,
        sortText: `!2${index.toString().padStart(3, '0')}`,
      }))
    );
    return suggestions;
  }

  const schemaType = getSchemaType(schema);
  if (schemaType === 'boolean') {
    suggestions.push(
      ...['true', 'false'].map((value, index) => ({
        label: value,
        kind: monaco.languages.CompletionItemKind.Value,
        detail: getSchemaTitle(schema) ?? getSchemaDescription(schema),
        insertText: value,
        range,
        sortText: `!2${index.toString().padStart(3, '0')}`,
      }))
    );
    return suggestions;
  }

  const preferredValues = [
    getSchemaDefault(schema),
    ...getSchemaExamples(schema),
  ].filter((value, index, collection) => {
    if (value === undefined || value === null) {
      return false;
    }

    return collection.findIndex((candidate) => candidate === value) === index;
  });

  for (const [index, value] of preferredValues.entries()) {
    suggestions.push({
      label: typeof value === 'string' ? value : toJsonLiteral(value),
      kind: monaco.languages.CompletionItemKind.Value,
      detail: 'Schema example',
      insertText: buildValueInsertText(value, isStringValueContext),
      range,
      sortText: `!3${index.toString().padStart(3, '0')}`,
    });
  }

  if (schemaType === 'object' || schemaType === 'array') {
    const snippetState: SnippetState = { nextTabStop: 1 };
    suggestions.push({
      label: schemaType === 'object' ? 'object' : 'array',
      kind: monaco.languages.CompletionItemKind.Snippet,
      detail:
        schemaType === 'object'
          ? 'Insert an object matching the schema'
          : 'Insert an array matching the schema',
      documentation: getSchemaDescription(schema),
      insertText: buildSchemaValueSnippet(
        schema,
        schemaCursor.rootSchema,
        snippetState
      ),
      insertTextRules:
        monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
      range,
      sortText: '!4schema',
    });
  }

  return suggestions;
}

function getCompletionLabel(
  item: import('monaco-editor').languages.CompletionItem
): string {
  return typeof item.label === 'string' ? item.label : item.label.label;
}

function dedupeSuggestions(
  suggestions: import('monaco-editor').languages.CompletionItem[]
) {
  const seen = new Set<string>();

  return suggestions.filter((item) => {
    const key = `${getCompletionLabel(item)}::${String(item.insertText ?? '')}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function buildCompletionSuggestions(
  monaco: MonacoModule,
  model: import('monaco-editor').editor.ITextModel,
  position: import('monaco-editor').Position,
  context: JsonEditorAutocompleteContext
): import('monaco-editor').languages.CompletionItem[] {
  const text = model.getValue();
  const offset = model.getOffsetAt(position);
  const tree = parseTree(text);
  const location = getLocation(text, offset);
  const node =
    tree && offset > 0 ? findNodeAtOffset(tree, offset - 1, true) : tree;
  const valueRange = getReplaceRange(monaco, model, position, node);
  const isStringValueContext =
    node?.type === 'string' && !location.isAtPropertyKey;
  const suggestions: import('monaco-editor').languages.CompletionItem[] = [];

  const activeEvaluator = resolveActiveEvaluator(context, tree, location.path);

  if (isEvaluatorNameLocation(location.path)) {
    suggestions.push(
      ...buildEvaluatorNameSuggestions(
        monaco,
        valueRange,
        context.evaluators,
        isStringValueContext
      )
    );
  }

  if (isSelectorPathLocation(location.path)) {
    suggestions.push(
      ...buildSelectorSuggestions(
        monaco,
        valueRange,
        context.steps,
        tree,
        isStringValueContext
      )
    );
  }

  const propertyKeyContext = getPropertyKeyContext(
    location.path,
    location.isAtPropertyKey
  );

  if (propertyKeyContext) {
    // Only treat as replacing when cursor is inside a quoted string node.
    // For bare text (typing without "), we need the leading " in the insert.
    const hasStringNode = node?.type === 'string';
    const replaceExistingKey = hasStringNode;

    const propertyRange =
      (hasStringNode
        ? getPropertyKeyReplaceRange(monaco, model, node)
        : null) ?? getDefaultRange(monaco, model, position);
    const schemaCursor = resolveSchemaAtJsonPath(
      context,
      activeEvaluator,
      propertyKeyContext.objectPath
    );
    const currentPropertyName =
      replaceExistingKey && typeof node?.value === 'string' ? node.value : null;

    suggestions.push(
      ...buildSchemaPropertySuggestions(
        monaco,
        propertyRange,
        schemaCursor,
        tree,
        propertyKeyContext.objectPath,
        replaceExistingKey,
        currentPropertyName,
        text,
        offset
      )
    );
  }

  // Only show value suggestions at actual value positions — not on blank lines,
  // closing brackets, or property key positions where they're confusing noise.
  const lineText = model.getLineContent(position.lineNumber);
  const isValuePosition =
    !propertyKeyContext && !location.isAtPropertyKey && isStringValueContext;
  if (isValuePosition) {
    const valueSchemaCursor = resolveSchemaAtJsonPath(
      context,
      activeEvaluator,
      location.path
    );

    suggestions.push(
      ...buildSchemaValueSuggestions(
        monaco,
        valueRange,
        valueSchemaCursor,
        isStringValueContext,
        typeof node?.value === 'string' ? node.value : undefined
      )
    );
  }

  return dedupeSuggestions(suggestions);
}

export function fixJsonCommas(text: string): string {
  // 1. Remove trailing commas before } or ]
  let fixed = text.replace(/,(\s*[}\]])/g, '$1');

  // 2. Insert missing commas (detected by jsonc-parser)
  const errors: ParseError[] = [];
  parseTree(fixed, errors);

  const commaErrors = errors
    .filter((e) => e.error === 6 /* CommaExpected */)
    .sort((a, b) => b.offset - a.offset);

  for (const error of commaErrors) {
    // Insert comma at end of previous value (before whitespace), not at
    // the start of the next token where jsonc-parser reports the error.
    let insertAt = error.offset;
    while (insertAt > 0 && /\s/.test(fixed[insertAt - 1])) {
      insertAt -= 1;
    }
    fixed = fixed.slice(0, insertAt) + ',' + fixed.slice(insertAt);
  }
  return fixed;
}

export function getJsonEditorCompletionItems(
  monaco: MonacoModule,
  model: import('monaco-editor').editor.ITextModel,
  position: import('monaco-editor').Position,
  context: JsonEditorAutocompleteContext
) {
  return buildCompletionSuggestions(monaco, model, position, context);
}

type EvaluatorNodeInfo = {
  name: string;
  nameNode: JsonNode;
  configNode: JsonNode | undefined;
  evaluatorNode: JsonNode;
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
        evaluatorNode,
      });
    }
  }

  for (const key of ['and', 'or'] as const) {
    const arrayNode = findNodeAtLocation(node, [key]);
    if (arrayNode?.type === 'array' && arrayNode.children) {
      for (const child of arrayNode.children) {
        collectEvaluatorNames(child, result);
      }
    }
  }

  const notNode = findNodeAtLocation(node, ['not']);
  if (notNode?.type === 'object') {
    collectEvaluatorNames(notNode, result);
  }
}

export function extractEvaluatorNames(text: string): Map<string, string> {
  const tree = parseTree(text);
  if (!tree) return new Map();

  const conditionNode = findNodeAtLocation(tree, ['condition']);
  const result = new Map<string, EvaluatorNodeInfo>();
  collectEvaluatorNames(conditionNode, result);

  const names = new Map<string, string>();
  for (const [key, info] of result) {
    names.set(key, info.name);
  }
  return names;
}

function getDefaultValueForSchema(propSchema: JsonSchema): unknown {
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

export function buildDefaultConfig(
  configSchema: unknown
): Record<string, unknown> {
  const schema = asSchema(configSchema);
  if (!schema) return {};

  const normalized = normalizeSchema(schema, schema);
  if (!normalized) return {};

  const properties = getSchemaProperties(normalized);
  const required = new Set(getSchemaRequiredProperties(normalized));
  const config: Record<string, unknown> = {};

  // Include ALL properties — required ones get type-appropriate defaults,
  // optional ones with explicit defaults get those defaults.
  for (const [propName, rawPropSchema] of Object.entries(properties)) {
    const propSchema = normalizeSchema(rawPropSchema, schema);
    if (!propSchema) continue;

    const explicitDefault = getSchemaDefault(propSchema);
    if (required.has(propName) || explicitDefault !== undefined) {
      config[propName] = getDefaultValueForSchema(propSchema);
    }
  }

  return config;
}

export function findEvaluatorConfigEdit(
  text: string,
  previousNames: Map<string, string>,
  evaluators: JsonEditorEvaluatorOption[] | undefined
): { offset: number; length: number; newText: string } | null {
  const tree = parseTree(text);
  if (!tree) return null;

  const conditionNode = findNodeAtLocation(tree, ['condition']);
  const result = new Map<string, EvaluatorNodeInfo>();
  collectEvaluatorNames(conditionNode, result);

  for (const [key, { name, configNode, nameNode }] of result) {
    const prevName = previousNames.get(key);
    if (prevName === undefined || prevName === name) continue;

    const evaluator = evaluators?.find((e) => e.id === name);
    if (!evaluator) continue;

    const defaultConfig = buildDefaultConfig(evaluator.configSchema);
    const configJson = JSON.stringify(defaultConfig, null, 2);

    if (configNode) {
      // Replace existing config
      return {
        offset: configNode.offset,
        length: configNode.length,
        newText: configJson,
      };
    }

    // No config property yet — insert after the name property.
    // Find the end of the "name": "value" property in the source text.
    const nameEnd = nameNode.offset + nameNode.length;
    return {
      offset: nameEnd,
      length: 0,
      newText: `,\n"config": ${configJson}`,
    };
  }

  return null;
}

export function findSteeringContextEdit(
  text: string,
  previousDecision: string | null
): { offset: number; length: number; newText: string } | null {
  const tree = parseTree(text);
  if (!tree) return null;

  const decisionNode = findNodeAtLocation(tree, ['action', 'decision']);
  if (!decisionNode || typeof decisionNode.value !== 'string') return null;

  const currentDecision = decisionNode.value;
  if (currentDecision === previousDecision) return null;

  if (currentDecision === 'steer') {
    // Add steering_context if missing
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
    // Remove steering_context when switching away from steer
    const actionNode = findNodeAtLocation(tree, ['action']);
    if (actionNode?.type === 'object' && actionNode.children) {
      for (const prop of actionNode.children) {
        const key = prop.children?.[0];
        if (key?.value === 'steering_context') {
          // Find range including the preceding comma
          let start = prop.offset;
          while (start > 0 && /[\s,]/.test(text[start - 1])) {
            start -= 1;
          }
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

const MAX_HINT_VALUES = 6;

function getStringValueAtPath(
  tree: JsonNode | undefined,
  path: JsonPath
): string | null {
  if (!tree) return null;
  const node = findNodeAtLocation(tree, path);
  return typeof node?.value === 'string' ? node.value : null;
}

export function getEmptyValueHints(
  monaco: MonacoModule,
  model: import('monaco-editor').editor.ITextModel,
  context: JsonEditorAutocompleteContext
): Array<{ range: import('monaco-editor').IRange; hint: string }> {
  const text = model.getValue();
  const tree = parseTree(text);
  if (!tree) return [];

  const hints: Array<{ range: import('monaco-editor').IRange; hint: string }> =
    [];

  // Hints for empty string values
  const emptyStringPattern = /:\s*""/g;
  let match;

  while ((match = emptyStringPattern.exec(text)) !== null) {
    const offset = match.index + match[0].length - 1;
    const location = getLocation(text, offset);
    if (location.isAtPropertyKey) continue;

    const pos = model.getPositionAt(offset);
    const range = new monaco.Range(
      pos.lineNumber,
      pos.column,
      pos.lineNumber,
      pos.column
    );

    const activeEvaluator = resolveActiveEvaluator(
      context,
      tree,
      location.path
    );

    if (isEvaluatorNameLocation(location.path) && context.evaluators?.length) {
      const names = context.evaluators.map((e) => e.id);
      const display = names.slice(0, MAX_HINT_VALUES);
      const hint =
        display.join('  |  ') +
        (names.length > MAX_HINT_VALUES ? '  | ...' : '');
      hints.push({ range, hint: `  ${hint}` });
      continue;
    }

    if (isSelectorPathLocation(location.path)) {
      hints.push({
        range,
        hint: '  *  |  input  |  output  |  context  |  ...',
      });
      continue;
    }

    const schemaCursor = resolveSchemaAtJsonPath(
      context,
      activeEvaluator,
      location.path
    );
    if (!schemaCursor.schema) continue;

    const enumValues = getSchemaEnumValues(schemaCursor.schema);
    if (enumValues.length > 0 && enumValues.length <= MAX_HINT_VALUES) {
      hints.push({
        range,
        hint: `  ${enumValues.map(String).join('  |  ')}`,
      });
    }
  }

  return hints;
}

// Default Monaco JSON mode configuration with completionItems disabled.
// We disable the built-in JSON completion provider to avoid duplicate suggestions
export function setupJsonEditorLanguageSupport(
  monaco: MonacoModule,
  context: JsonEditorAutocompleteContext
) {
  const jsonDefaults = (
    monaco.languages.json as unknown as {
      jsonDefaults?: {
        setDiagnosticsOptions: (options: {
          validate: boolean;
          allowComments: boolean;
          schemas: Array<{
            fileMatch: string[];
            uri: string;
            schema: JsonSchema;
          }>;
        }) => void;
      };
    }
  ).jsonDefaults;

  // Validate JSON syntax only and suppress Monaco's built-in completions.
  // Passing a restrictive schema (type:object + additionalProperties:false)
  // prevents the worker-based provider from suggesting "$schema" and other
  // JSON meta-keywords. Our custom provider handles all domain completions.
  jsonDefaults?.setDiagnosticsOptions({
    validate: true,
    allowComments: false,
    schemas: [
      {
        uri: 'internal://control-definition/schema.json',
        fileMatch: ['*'],
        schema: { type: 'object', additionalProperties: true },
      },
    ],
  });

  const jsonMode = (
    monaco.languages.json as unknown as {
      jsonDefaults?: {
        setModeConfiguration?: (config: {
          completionItems?: { enable?: boolean };
        }) => void;
      };
    }
  ).jsonDefaults;
  jsonMode?.setModeConfiguration?.({ completionItems: { enable: false } });

  const hoverDisposable = monaco.languages.registerHoverProvider('json', {
    provideHover(model, position) {
      if (model.uri.toString() !== context.modelUri) return null;
      if (!context.schema) return null;

      const text = model.getValue();
      const offset = model.getOffsetAt(position);
      const tree = parseTree(text);
      const location = getLocation(text, offset);
      if (!location.path.length) return null;

      const rootSchema = asSchema(context.schema);
      const activeEvaluator = resolveActiveEvaluator(
        context,
        tree,
        location.path
      );
      const cursor = resolveSchemaAtJsonPath(
        context,
        activeEvaluator,
        location.isAtPropertyKey ? location.path.slice(0, -1) : location.path
      );

      // For property keys, show the property's schema description
      if (location.isAtPropertyKey) {
        const propName = location.path[location.path.length - 1];
        if (typeof propName !== 'string' || !cursor.schema) return null;
        const propSchema = getSchemaAtProperty(
          cursor.schema,
          propName,
          cursor.rootSchema
        );
        const desc = getSchemaDescription(propSchema);
        const title = getSchemaTitle(propSchema);
        if (!desc && !title) return null;

        const word = model.getWordAtPosition(position);
        const range = word
          ? new monaco.Range(
              position.lineNumber,
              word.startColumn,
              position.lineNumber,
              word.endColumn
            )
          : undefined;

        return {
          range,
          contents: [
            {
              value: `**${title ?? propName}**${desc ? '\n\n' + desc : ''}`,
            },
          ],
        };
      }

      // For values, show the value's schema info
      if (cursor.schema) {
        const desc = getSchemaDescription(cursor.schema);
        const title = getSchemaTitle(cursor.schema);
        const enumVals = getSchemaEnumValues(cursor.schema);
        if (!desc && !title && enumVals.length === 0) return null;

        const parts: string[] = [];
        if (title) parts.push(`**${title}**`);
        if (desc) parts.push(desc);
        if (enumVals.length > 0)
          parts.push(`Values: \`${enumVals.join('` | `')}\``);

        const word = model.getWordAtPosition(position);
        const range = word
          ? new monaco.Range(
              position.lineNumber,
              word.startColumn,
              position.lineNumber,
              word.endColumn
            )
          : undefined;

        return {
          range,
          contents: [{ value: parts.join('\n\n') }],
        };
      }

      return null;
    },
  });

  const disposable = monaco.languages.registerCompletionItemProvider('json', {
    triggerCharacters: COMPLETION_TRIGGER_CHARACTERS,
    provideCompletionItems(model, position) {
      if (model.uri.toString() !== context.modelUri) {
        return { suggestions: [] };
      }

      return {
        suggestions: getJsonEditorCompletionItems(
          monaco,
          model,
          position,
          context
        ),
      };
    },
  });

  const codeActionDisposable = registerConditionCodeActions(monaco, context);

  return () => {
    hoverDisposable.dispose();
    disposable.dispose();
    codeActionDisposable.dispose();
  };
}

// ---------------------------------------------------------------------------
// Condition Code Actions (lightbulb refactoring)
// ---------------------------------------------------------------------------

const LEAF_CONDITION_TEMPLATE = {
  selector: { path: '*' },
  evaluator: { name: '', config: {} },
};

function findConditionNodeAtOffset(
  tree: JsonNode | undefined,
  offset: number
): {
  node: JsonNode;
  isLeaf: boolean;
  isArray: boolean;
  arrayKey: string | null;
} | null {
  if (!tree) return null;

  const conditionNode = findNodeAtLocation(tree, ['condition']);
  if (!conditionNode) return null;

  return findConditionAtOffset(conditionNode, offset);
}

function findConditionAtOffset(
  node: JsonNode,
  offset: number
): {
  node: JsonNode;
  isLeaf: boolean;
  isArray: boolean;
  arrayKey: string | null;
} | null {
  if (offset < node.offset || offset > node.offset + node.length) return null;

  if (node.type === 'object' && node.children) {
    for (const prop of node.children) {
      const key = prop.children?.[0]?.value;
      const value = prop.children?.[1];
      if (!value) continue;

      if (key === 'and' || key === 'or') {
        if (value.type === 'array' && value.children) {
          // Check if offset is inside an array item
          for (const item of value.children) {
            const inner = findConditionAtOffset(item, offset);
            if (inner) return inner;
          }
          // Offset is in the array but not inside a specific item
          if (offset >= value.offset && offset <= value.offset + value.length) {
            return {
              node,
              isLeaf: false,
              isArray: true,
              arrayKey: key as string,
            };
          }
        }
      } else if (key === 'not' && value.type === 'object') {
        const inner = findConditionAtOffset(value, offset);
        if (inner) return inner;
      }
    }

    // We're on this object node itself
    const hasSelector = !!findNodeAtLocation(node, ['selector']);
    const hasEvaluator = !!findNodeAtLocation(node, ['evaluator']);
    const hasAnd = !!findNodeAtLocation(node, ['and']);
    const hasOr = !!findNodeAtLocation(node, ['or']);
    const hasNot = !!findNodeAtLocation(node, ['not']);
    const isLeaf = (hasSelector || hasEvaluator) && !hasAnd && !hasOr;

    return {
      node,
      isLeaf,
      isArray: false,
      arrayKey: hasAnd ? 'and' : hasOr ? 'or' : hasNot ? 'not' : null,
    };
  }

  return null;
}

function registerConditionCodeActions(
  monaco: MonacoModule,
  context: JsonEditorAutocompleteContext
) {
  return monaco.languages.registerCodeActionProvider('json', {
    provideCodeActions(model, range) {
      if (model.uri.toString() !== context.modelUri)
        return { actions: [], dispose() {} };
      if (context.mode !== 'control') return { actions: [], dispose() {} };

      const text = model.getValue();
      const tree = parseTree(text);
      if (!tree) return { actions: [], dispose() {} };

      const offset = model.getOffsetAt(range.getStartPosition());
      const condCtx = findConditionNodeAtOffset(tree, offset);
      if (!condCtx) return { actions: [], dispose() {} };

      const actions: import('monaco-editor').languages.CodeAction[] = [];
      const { node, isLeaf, isArray, arrayKey } = condCtx;

      const candidates: (
        | import('monaco-editor').languages.CodeAction
        | null
      )[] = [];

      if (isLeaf) {
        candidates.push(
          buildNodeTransformAction(
            monaco,
            model,
            node,
            'Wrap in AND (add another condition)',
            (p) => ({ and: [p, LEAF_CONDITION_TEMPLATE] })
          ),
          buildNodeTransformAction(
            monaco,
            model,
            node,
            'Wrap in OR (add another condition)',
            (p) => ({ or: [p, LEAF_CONDITION_TEMPLATE] })
          ),
          buildNodeTransformAction(monaco, model, node, 'Wrap in NOT', (p) => ({
            not: p,
          }))
        );
      }

      if (isArray && (arrayKey === 'and' || arrayKey === 'or')) {
        const otherKey = arrayKey === 'and' ? 'or' : 'and';
        candidates.push(
          buildNodeTransformAction(
            monaco,
            model,
            node,
            `Add condition to ${arrayKey.toUpperCase()}`,
            (p) => {
              const o = p as Record<string, unknown>;
              const a = o[arrayKey];
              if (!Array.isArray(a)) return undefined;
              return { ...o, [arrayKey]: [...a, LEAF_CONDITION_TEMPLATE] };
            }
          ),
          buildNodeTransformAction(
            monaco,
            model,
            node,
            `Convert ${arrayKey.toUpperCase()} to ${otherKey.toUpperCase()}`,
            (p) => {
              const o = p as Record<string, unknown>;
              const a = o[arrayKey];
              delete o[arrayKey];
              return { ...o, [otherKey]: a };
            }
          )
        );
      }

      if (arrayKey === 'not') {
        candidates.push(
          buildNodeTransformAction(
            monaco,
            model,
            node,
            'Remove NOT (unwrap)',
            (p) => (p as Record<string, unknown>).not
          )
        );
      }

      for (const action of candidates) {
        if (action) actions.push(action);
      }

      return { actions, dispose() {} };
    },
  });
}

function buildNodeTransformAction(
  monaco: MonacoModule,
  model: import('monaco-editor').editor.ITextModel,
  node: JsonNode,
  title: string,
  transform: (parsed: unknown) => unknown
): import('monaco-editor').languages.CodeAction | null {
  // Parse the full document, apply the transform to the target node,
  // then re-serialize the whole document. This produces a single edit
  // that replaces the entire content with properly formatted JSON,
  // making undo a clean single-step revert.
  const fullText = model.getValue();
  const nodeText = fullText.substring(node.offset, node.offset + node.length);
  let parsed: unknown;
  try {
    parsed = JSON.parse(nodeText);
  } catch {
    return null;
  }

  const result = transform(parsed);
  if (result === undefined) return null;

  // Rebuild full document with the transformed node
  const newNodeText = JSON.stringify(result);
  const rawDoc =
    fullText.substring(0, node.offset) +
    newNodeText +
    fullText.substring(node.offset + node.length);

  let newText: string;
  try {
    newText = JSON.stringify(JSON.parse(rawDoc), null, 2);
  } catch {
    // Fallback: just replace the node
    newText =
      fullText.substring(0, node.offset) +
      JSON.stringify(result, null, 2) +
      fullText.substring(node.offset + node.length);
  }

  const fullRange = model.getFullModelRange();

  return {
    title,
    kind: 'refactor',
    edit: {
      edits: [
        {
          resource: model.uri,
          textEdit: {
            range: new monaco.Range(
              fullRange.startLineNumber,
              fullRange.startColumn,
              fullRange.endLineNumber,
              fullRange.endColumn
            ),
            text: newText,
          },
          versionId: model.getVersionId(),
        },
      ],
    },
  };
}
