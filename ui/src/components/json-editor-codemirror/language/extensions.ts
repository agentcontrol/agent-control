import {
  acceptCompletion,
  autocompletion,
  closeCompletion,
  type Completion,
  completionKeymap,
  insertCompletionText,
  moveCompletionSelection,
  pickedCompletion,
  snippetCompletion,
  startCompletion,
} from '@codemirror/autocomplete';
import {
  type Extension,
  Prec,
  type Range,
  RangeSetBuilder,
} from '@codemirror/state';
import {
  Decoration,
  EditorView,
  gutter,
  GutterMarker,
  hoverTooltip,
  keymap,
  ViewPlugin,
  type ViewUpdate,
  WidgetType,
} from '@codemirror/view';
import {
  findNodeAtLocation,
  findNodeAtOffset,
  getLocation,
  type Node as JsonNode,
  parseTree,
} from 'jsonc-parser';

export {
  buildCodeMirrorInlineServerValidationErrorsExtension,
  canRenderInlineServerValidationError,
  setInlineServerValidationErrorsEffect,
} from './inline-server-validation';

import {
  getEnumValues,
  getScopeFilters,
  isEvaluatorNameLocation,
  isSelectorPathLocation,
  parseJsonTree,
  resolveActiveEvaluator,
  resolveSchemaAtJsonPath,
} from './context';
import {
  getJsonInsertTextForSchemaPropertyValue,
  getSchemaAtProperty,
  getSchemaDescription,
  getSchemaProperties,
  getSchemaTitle,
  getSchemaType,
  normalizeSchema,
} from './schema';
import {
  type JsonEditorCodeMirrorContext,
  MAX_HINT_VALUES,
  ROOT_SELECTOR_PATHS,
} from './types';

/**
 * CodeMirror uses `state.sliceDoc(from, to)` as the fuzzy-filter query.
 * Property-key contexts used `from === to === pos`, so the query was always
 * empty and every completion matched (see FuzzyMatcher empty pattern).
 */
function getCompletionFilterRange(
  text: string,
  pos: number,
  location: { isAtPropertyKey: boolean },
  valueNode: JsonNode | undefined
): { from: number; to: number } {
  const tree = parseTree(text);
  const isStringValueContext =
    !location.isAtPropertyKey && valueNode?.type === 'string';

  if (isStringValueContext && valueNode) {
    return {
      from: valueNode.offset + 1,
      to: valueNode.offset + Math.max(valueNode.length - 1, 1),
    };
  }

  if (location.isAtPropertyKey && tree && pos > 0) {
    const keyNode = findNodeAtOffset(tree, pos - 1, true);
    if (keyNode?.type === 'string' && pos >= keyNode.offset + 1) {
      return { from: keyNode.offset + 1, to: pos };
    }
  }

  return { from: pos, to: pos };
}

function dedupeCompletions(items: Completion[]): Completion[] {
  const seen = new Set<string>();
  const out: Completion[] = [];
  for (const item of items) {
    const key = `${item.label}|${item.type ?? ''}|${item.detail ?? ''}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(item);
  }
  return out;
}

function _getWordBounds(
  text: string,
  offset: number
): { from: number; to: number } {
  let from = offset;
  let to = offset;
  while (from > 0 && /[\w:-]/.test(text[from - 1] ?? '')) from -= 1;
  while (to < text.length && /[\w:-]/.test(text[to] ?? '')) to += 1;
  return { from, to };
}

function toJsonLiteral(value: unknown): string {
  return typeof value === 'string' ? JSON.stringify(value) : String(value);
}

/** Escape `$`, `}`, `\` for CodeMirror snippet templates (see Monaco `escapeSnippetValue`). */
function escapeCodeMirrorSnippetText(s: string): string {
  return s.replace(/[\\$}]/g, '\\$&');
}

/**
 * When the user already typed the opening `"` of a property key, inserts must not
 * include another leading `"` or acceptance produces `""json_schema": …`.
 */
function isInsideQuotedPropertyKey(
  text: string,
  pos: number,
  isAtPropertyKey: boolean
): boolean {
  if (!isAtPropertyKey || pos <= 0) return false;
  const tree = parseTree(text);
  if (!tree) return false;
  const node = findNodeAtOffset(tree, pos - 1, true);
  return node?.type === 'string' && pos >= node.offset + 1;
}

/**
 * - Eat a typed closing `"` after a partial property key (filter range ends at cursor).
 * - Optionally insert `,` before the next sibling when the inserted value is single-line
 *   (skip multiline object/array snippets so we don't break cursor/snippet fields).
 */
function wrapPropertyCompletionApply(
  completion: Completion,
  options: { insideQuotedKey: boolean; autoCommaAfter: boolean }
): Completion {
  if (typeof completion.apply !== 'function') {
    return completion;
  }
  const innerApply = completion.apply;
  return {
    ...completion,
    apply: (view, comp, from, to) => {
      let end = to;
      if (options.insideQuotedKey && view.state.sliceDoc(to, to + 1) === '"') {
        end = to + 1;
      }
      const docLenBefore = view.state.doc.length;
      const replacedLen = end - from;
      innerApply(view, comp, from, end);

      if (!options.autoCommaAfter) return;

      // Snippet apply can leave main selection at the replace start (`from`) instead
      // of after the inserted text — inserting `,` at `main.head` then yields `",enabled`.
      const docLenAfter = view.state.doc.length;
      const insertLen = docLenAfter - docLenBefore + replacedLen;
      const valueEnd = from + insertLen;

      let scan = valueEnd;
      const doc = view.state.doc;
      while (scan < doc.length) {
        const ch = doc.sliceString(scan, scan + 1);
        if (!/\s/.test(ch)) break;
        scan += 1;
      }
      const next = scan < doc.length ? doc.sliceString(scan, scan + 1) : '';
      if (next && next !== '}' && next !== ']' && next !== ',') {
        view.dispatch({
          changes: { from: valueEnd, to: valueEnd, insert: ',' },
          selection: { anchor: valueEnd + 1 },
        });
      }
    },
  };
}

function getPropertySuggestions(
  text: string,
  context: JsonEditorCodeMirrorContext,
  path: Array<string | number>,
  offset: number,
  isAtPropertyKey: boolean
): Completion[] {
  const tree = parseJsonTree(text);
  const activeEvaluator = resolveActiveEvaluator(context, tree, path);
  const objectPath = path.slice(0, -1);
  const schemaCursor = resolveSchemaAtJsonPath(
    context,
    activeEvaluator,
    objectPath
  );
  if (!schemaCursor.schema) return [];

  const objectNode = tree ? findNodeAtLocation(tree, objectPath) : undefined;
  const existingKeys = new Set<string>();
  if (objectNode?.type === 'object' && objectNode.children) {
    for (const child of objectNode.children) {
      const keyNode = child.children?.[0];
      if (typeof keyNode?.value === 'string') existingKeys.add(keyNode.value);
    }
  } else {
    const nearText = text.slice(
      Math.max(0, offset - 800),
      Math.min(text.length, offset + 800)
    );
    for (const match of nearText.matchAll(/"([^"\\]+)"\s*:/g)) {
      const key = match[1];
      if (key) existingKeys.add(key);
    }
  }

  const insideQuotedKey = isInsideQuotedPropertyKey(
    text,
    offset,
    isAtPropertyKey
  );

  const suggestions: Completion[] = [];
  const properties = getSchemaProperties(schemaCursor.schema);
  for (const [propertyName, rawSchema] of Object.entries(properties)) {
    if (existingKeys.has(propertyName)) continue;
    const normalized = normalizeSchema(rawSchema, schemaCursor.rootSchema);
    const type = getSchemaType(normalized) ?? 'string';
    const valueInsert = getJsonInsertTextForSchemaPropertyValue(
      rawSchema,
      schemaCursor.rootSchema
    );
    const escapedName = escapeCodeMirrorSnippetText(propertyName);
    const snippetBody = insideQuotedKey
      ? `${escapedName}": ${valueInsert}`
      : `"${escapedName}": ${valueInsert}`;
    const base = snippetCompletion(snippetBody, {
      label: propertyName,
      type: 'property',
      detail: type,
    });
    const autoCommaAfter = !valueInsert.includes('\n');
    suggestions.push({
      ...wrapPropertyCompletionApply(base, {
        insideQuotedKey,
        autoCommaAfter,
      }),
      info: getSchemaDescription(normalized) ?? undefined,
    } as Completion);
  }
  return suggestions;
}

function getValueSuggestions(
  text: string,
  context: JsonEditorCodeMirrorContext,
  path: Array<string | number>,
  isStringValueContext: boolean
): Completion[] {
  const tree = parseJsonTree(text);
  if (isEvaluatorNameLocation(path) && context.evaluators?.length) {
    return context.evaluators.map((item) => ({
      label: item.id,
      type: 'constant',
      detail: item.description ?? undefined,
      info: item.description ?? undefined,
      apply: (
        view: EditorView,
        completion: Completion,
        from: number,
        to: number
      ) => {
        const insert = isStringValueContext ? item.id : JSON.stringify(item.id);
        view.dispatch({
          ...insertCompletionText(view.state, insert, from, to),
          annotations: pickedCompletion.of(completion),
        });
        closeCompletion(view);
      },
    }));
  }

  if (isSelectorPathLocation(path)) {
    const { stepNames, stepTypes } = getScopeFilters(tree);
    const stepPathSuggestions = context.steps
      ?.filter((step) =>
        stepTypes.length > 0 ? step.type && stepTypes.includes(step.type) : true
      )
      .filter((step) =>
        stepNames.length > 0 ? step.name && stepNames.includes(step.name) : true
      )
      .map((step) => ({
        label: step.name ?? '',
        detail: step.type ?? '',
        rank: 60,
      }))
      .filter((item) => item.label.length > 0);

    const base = ROOT_SELECTOR_PATHS.map((label) => ({
      label,
      detail: 'selector root',
      rank: 100,
    }));
    return dedupeCompletions(
      [...base, ...(stepPathSuggestions ?? [])]
        .sort((a, b) => b.rank - a.rank)
        .map((item) => ({
          label: item.label,
          type: 'variable' as const,
          detail: item.detail,
          info: item.detail,
          apply: (
            view: EditorView,
            completion: Completion,
            from: number,
            to: number
          ) => {
            const insert = isStringValueContext
              ? item.label
              : JSON.stringify(item.label);
            view.dispatch({
              ...insertCompletionText(view.state, insert, from, to),
              annotations: pickedCompletion.of(completion),
            });
          },
        }))
    );
  }

  const activeEvaluator = resolveActiveEvaluator(context, tree, path);
  const cursor = resolveSchemaAtJsonPath(context, activeEvaluator, path);
  const enumValues = getEnumValues(cursor.schema);
  if (enumValues.length === 0) return [];
  return enumValues.map((value) => ({
    label: String(value),
    type: 'enum',
    info: typeof value === 'string' ? `Enum value: ${value}` : 'Enum value',
    apply: (
      view: EditorView,
      completion: Completion,
      from: number,
      to: number
    ) => {
      const insert =
        isStringValueContext && typeof value === 'string'
          ? value
          : toJsonLiteral(value);
      view.dispatch({
        ...insertCompletionText(view.state, insert, from, to),
        annotations: pickedCompletion.of(completion),
      });
    },
  }));
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
  if (node.type !== 'object' || !node.children) return null;

  for (const prop of node.children) {
    const key = prop.children?.[0]?.value;
    const value = prop.children?.[1];
    if (!value) continue;
    if (
      (key === 'and' || key === 'or') &&
      value.type === 'array' &&
      value.children
    ) {
      for (const item of value.children) {
        const inner = findConditionAtOffset(item, offset);
        if (inner) return inner;
      }
      if (offset >= value.offset && offset <= value.offset + value.length) {
        return { node, isLeaf: false, isArray: true, arrayKey: key as string };
      }
    } else if (key === 'not' && value.type === 'object') {
      const inner = findConditionAtOffset(value, offset);
      if (inner) return inner;
    }
  }

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

type RefactorAction = {
  label: string;
  apply: (view: EditorView) => void;
};

const refactorCompletionArmed = new WeakMap<EditorView, boolean>();

function buildConditionRefactorActions(
  text: string,
  offset: number
): RefactorAction[] {
  const tree = parseTree(text);
  if (!tree) return [];
  const conditionNode = findNodeAtLocation(tree, ['condition']);
  if (!conditionNode) return [];
  const condCtx = findConditionAtOffset(conditionNode, offset);
  if (!condCtx) return [];

  const { node, isLeaf, isArray, arrayKey } = condCtx;
  const nodeText = text.substring(node.offset, node.offset + node.length);
  let parsedNode: unknown;
  try {
    parsedNode = JSON.parse(nodeText);
  } catch {
    return [];
  }

  const applyNodeTransform = (
    transform: (parsed: unknown) => unknown
  ): string | null => {
    const transformed = transform(parsedNode);
    if (transformed === undefined) return null;
    const rawDoc =
      text.substring(0, node.offset) +
      JSON.stringify(transformed) +
      text.substring(node.offset + node.length);
    try {
      return JSON.stringify(JSON.parse(rawDoc), null, 2);
    } catch {
      return (
        text.substring(0, node.offset) +
        JSON.stringify(transformed, null, 2) +
        text.substring(node.offset + node.length)
      );
    }
  };

  const actions: RefactorAction[] = [];
  if (isLeaf) {
    actions.push(
      {
        label: 'Wrap in AND (add another condition)',
        apply: (view) => {
          const next = applyNodeTransform((p) => ({
            and: [
              p as Record<string, unknown>,
              { selector: { path: '*' }, evaluator: { name: '', config: {} } },
            ],
          }));
          if (!next) return;
          view.dispatch({
            changes: { from: 0, to: view.state.doc.length, insert: next },
          });
        },
      },
      {
        label: 'Wrap in OR (add another condition)',
        apply: (view) => {
          const next = applyNodeTransform((p) => ({
            or: [
              p as Record<string, unknown>,
              { selector: { path: '*' }, evaluator: { name: '', config: {} } },
            ],
          }));
          if (!next) return;
          view.dispatch({
            changes: { from: 0, to: view.state.doc.length, insert: next },
          });
        },
      },
      {
        label: 'Wrap in NOT',
        apply: (view) => {
          const next = applyNodeTransform((p) => ({ not: p }));
          if (!next) return;
          view.dispatch({
            changes: { from: 0, to: view.state.doc.length, insert: next },
          });
        },
      }
    );
  }

  if (isArray && (arrayKey === 'and' || arrayKey === 'or')) {
    const otherKey = arrayKey === 'and' ? 'or' : 'and';
    actions.push(
      {
        label: `Add condition to ${arrayKey.toUpperCase()}`,
        apply: (view) => {
          const next = applyNodeTransform((p) => {
            const obj = p as Record<string, unknown>;
            const arr = obj[arrayKey];
            if (!Array.isArray(arr)) return undefined;
            return {
              ...obj,
              [arrayKey]: [
                ...arr,
                {
                  selector: { path: '*' },
                  evaluator: { name: '', config: {} },
                },
              ],
            };
          });
          if (!next) return;
          view.dispatch({
            changes: { from: 0, to: view.state.doc.length, insert: next },
          });
        },
      },
      {
        label: `Convert ${arrayKey.toUpperCase()} to ${otherKey.toUpperCase()}`,
        apply: (view) => {
          const next = applyNodeTransform((p) => {
            const obj = p as Record<string, unknown>;
            const arr = obj[arrayKey];
            delete obj[arrayKey];
            return { ...obj, [otherKey]: arr };
          });
          if (!next) return;
          view.dispatch({
            changes: { from: 0, to: view.state.doc.length, insert: next },
          });
        },
      }
    );
  }

  if (arrayKey === 'not') {
    actions.push({
      label: 'Remove NOT (unwrap)',
      apply: (view) => {
        const next = applyNodeTransform(
          (p) => (p as Record<string, unknown>).not
        );
        if (!next) return;
        view.dispatch({
          changes: { from: 0, to: view.state.doc.length, insert: next },
        });
      },
    });
  }

  return actions;
}

function _toRefactorCompletions(actions: RefactorAction[]): Completion[] {
  return actions.map((action) => ({
    label: action.label,
    type: 'method',
    apply: (view) => {
      action.apply(view);
      closeCompletion(view);
    },
  }));
}

type RefactorContext = {
  from: number;
  to: number;
  actions: RefactorAction[];
};

function getRefactorContext(
  text: string,
  offset: number,
  mode: JsonEditorCodeMirrorContext['mode']
): RefactorContext | null {
  if (mode !== 'control') return null;
  const tree = parseTree(text);
  if (!tree) return null;
  const conditionNode = findNodeAtLocation(tree, ['condition']);
  if (!conditionNode) return null;
  const condCtx = findConditionAtOffset(conditionNode, offset);
  if (!condCtx) return null;
  const actions = buildConditionRefactorActions(text, offset);
  if (actions.length === 0) return null;
  return {
    from: condCtx.node.offset,
    to: condCtx.node.offset + condCtx.node.length,
    actions,
  };
}

class LightbulbGutterMarker extends GutterMarker {
  toDOM(): HTMLElement {
    const span = document.createElement('span');
    span.textContent = '💡';
    span.title = 'Show refactor actions';
    span.style.cursor = 'pointer';
    span.style.opacity = '0.9';
    return span;
  }
}

class HintWidget extends WidgetType {
  constructor(private readonly hint: string) {
    super();
  }

  toDOM(): HTMLElement {
    const span = document.createElement('span');
    span.style.color = 'var(--mantine-color-gray-5)';
    span.style.fontStyle = 'italic';
    span.style.pointerEvents = 'none';
    span.textContent = this.hint;
    return span;
  }
}

function getHintForPath(
  text: string,
  path: Array<string | number>,
  context: JsonEditorCodeMirrorContext
): string | null {
  // Avoid showing hint widgets for fields that already have a good dropdown UX.
  if (isEvaluatorNameLocation(path)) {
    return null;
  }

  // Avoid showing the enum value hint widget for action decision because it
  // duplicates/competes with the dropdown UI (user-reported).
  // This hint widget is only shown for empty string values (see _createHintsExtension).
  const last = path[path.length - 1];
  if (
    context.mode === 'control' &&
    last === 'decision' &&
    path.includes('action')
  ) {
    return null;
  }

  const tree = parseJsonTree(text);
  if (isEvaluatorNameLocation(path) && context.evaluators?.length) {
    const display = context.evaluators
      .map((item) => item.id)
      .slice(0, MAX_HINT_VALUES);
    return `  ${display.join('  |  ')}${context.evaluators.length > MAX_HINT_VALUES ? '  | ...' : ''}`;
  }

  if (isSelectorPathLocation(path)) {
    return '  *  |  input  |  output  |  context  |  ...';
  }

  const activeEvaluator = resolveActiveEvaluator(context, tree, path);
  const cursor = resolveSchemaAtJsonPath(context, activeEvaluator, path);
  const enumValues = getEnumValues(cursor.schema);
  if (enumValues.length > 0 && enumValues.length <= MAX_HINT_VALUES) {
    return `  ${enumValues.map(String).join('  |  ')}`;
  }
  return null;
}

/**
 * `activateOnTyping` often does not reopen completions after Backspace.
 * Also reopen when the user edits inside a JSON string that has value
 * suggestions (enums, evaluator name, selector path), including partial text
 * like `"s"` after deleting `"sdk"`.
 *
 * Only runs for direct typing/paste/delete — not programmatic doc updates
 * (for example default `config` injection after an evaluator rename).
 */
function _createAutocompleteOpenWhenValueSuggestionsAfterEditExtension(
  context: JsonEditorCodeMirrorContext
): Extension {
  return ViewPlugin.fromClass(
    class {
      private openQueued = false;

      update(update: ViewUpdate) {
        if (!update.docChanged) return;
        if (
          update.transactions.some((tr) => tr.isUserEvent('input.complete'))
        ) {
          return;
        }
        // Ignore programmatic doc changes (e.g. evaluator `config` auto-fill); those
        // must not queue another completion — the dropdown would pop right back.
        if (
          !update.transactions.some(
            (tr) =>
              tr.isUserEvent('input.type') ||
              tr.isUserEvent('input.paste') ||
              tr.isUserEvent('input.drop') ||
              tr.isUserEvent('delete')
          )
        ) {
          return;
        }

        const view = update.view;
        const pos = view.state.selection.main.head;
        const text = view.state.doc.toString();

        const location = getLocation(text, pos);
        if (!location.path.length || location.isAtPropertyKey) return;

        const tree = parseTree(text);
        if (!tree) return;

        const valueNode = findNodeAtLocation(tree, location.path);
        if (!valueNode || valueNode.type !== 'string') return;
        if (typeof valueNode.value !== 'string') return;

        // Ensure the cursor is inside the editable portion of the string
        // (between the quotes) before opening.
        const innerFrom = valueNode.offset + 1;
        const innerTo = valueNode.offset + Math.max(valueNode.length - 1, 1);
        if (pos < innerFrom || pos > innerTo) return;

        const options = getValueSuggestions(
          text,
          context,
          location.path,
          true /* isStringValueContext */
        );
        if (!options || options.length === 0) return;

        // CodeMirror forbids dispatching while an update is in progress.
        // Queue the completion open to the next tick.
        if (this.openQueued) return;
        this.openQueued = true;
        window.setTimeout(() => {
          try {
            startCompletion(view);
          } finally {
            this.openQueued = false;
          }
        }, 0);
      }
    }
  );
}

function _createHintsExtension(
  context: JsonEditorCodeMirrorContext
): Extension {
  return ViewPlugin.fromClass(
    class {
      decorations = Decoration.none;

      constructor(view: EditorView) {
        this.decorations = this.buildDecorations(view);
      }

      update(update: {
        docChanged: boolean;
        viewportChanged: boolean;
        view: EditorView;
      }) {
        if (update.docChanged || update.viewportChanged) {
          this.decorations = this.buildDecorations(update.view);
        }
      }

      buildDecorations(view: EditorView) {
        const text = view.state.doc.toString();
        const tree = parseJsonTree(text);
        if (!tree) return Decoration.none;

        const emptyStringPattern = /:\s*""/g;
        const ranges: Range<Decoration>[] = [];
        let match: RegExpExecArray | null;
        while ((match = emptyStringPattern.exec(text)) !== null) {
          const quoteOffset = match.index + match[0].length - 1;
          const location = getLocation(text, quoteOffset);
          if (location.isAtPropertyKey) continue;
          const hint = getHintForPath(text, location.path, context);
          if (!hint) continue;
          ranges.push(
            Decoration.widget({ side: 1, widget: new HintWidget(hint) }).range(
              quoteOffset + 1
            )
          );
        }
        return Decoration.set(ranges, true);
      }
    },
    { decorations: (value) => value.decorations }
  );
}

function _createHoverExtension(
  context: JsonEditorCodeMirrorContext
): Extension {
  return hoverTooltip((view, pos) => {
    const text = view.state.doc.toString();
    const tree = parseJsonTree(text);
    const location = getLocation(text, pos);
    if (!location.path.length) return null;

    const activeEvaluator = resolveActiveEvaluator(
      context,
      tree,
      location.path
    );
    const path = location.isAtPropertyKey
      ? location.path.slice(0, -1)
      : location.path;
    const cursor = resolveSchemaAtJsonPath(context, activeEvaluator, path);

    let title: string | null = null;
    let description: string | null = null;
    let enumValues: unknown[] = [];

    if (location.isAtPropertyKey) {
      const propName = location.path[location.path.length - 1];
      if (typeof propName !== 'string' || !cursor.schema) return null;
      const propSchema = getSchemaAtProperty(
        cursor.schema,
        propName,
        cursor.rootSchema
      );
      title = getSchemaTitle(propSchema);
      description = getSchemaDescription(propSchema);
      enumValues = getEnumValues(propSchema);
    } else {
      title = getSchemaTitle(cursor.schema);
      description = getSchemaDescription(cursor.schema);
      enumValues = getEnumValues(cursor.schema);
    }

    if (!title && !description && enumValues.length === 0) return null;

    const dom = document.createElement('div');
    dom.style.maxWidth = '420px';
    dom.style.whiteSpace = 'normal';
    if (title) {
      const heading = document.createElement('div');
      heading.style.fontWeight = '600';
      heading.textContent = title;
      dom.appendChild(heading);
    }
    if (description) {
      const body = document.createElement('div');
      body.style.marginTop = title ? '4px' : '0';
      body.textContent = description;
      dom.appendChild(body);
    }
    if (enumValues.length > 0) {
      const enumLine = document.createElement('div');
      enumLine.style.marginTop = '6px';
      enumLine.textContent = `Values: ${enumValues.map(String).join(' | ')}`;
      dom.appendChild(enumLine);
    }
    return { pos, end: pos, create: () => ({ dom }) };
  });
}

const completionNavigationKeymap = Prec.highest(
  keymap.of([
    { key: 'ArrowDown', run: moveCompletionSelection(true) },
    { key: 'ArrowUp', run: moveCompletionSelection(false) },
    { key: 'Enter', run: acceptCompletion },
  ])
);

export function buildCodeMirrorJsonExtensions(
  context: JsonEditorCodeMirrorContext,
  options?: {
    enableHoverExtension?: boolean;
    enableHintsExtension?: boolean;
  }
): Extension[] {
  const enableHoverExtension = options?.enableHoverExtension ?? true;
  // Hints are intentionally off by default — dropdown completions cover the UX.
  const enableHintsExtension = options?.enableHintsExtension ?? false;

  return [
    autocompletion({
      activateOnTyping: true,
      override: [
        (completionContext) => {
          const text = completionContext.state.doc.toString();
          const location = getLocation(text, completionContext.pos);
          const tree = parseTree(text);
          const valueNode = tree
            ? findNodeAtLocation(tree, location.path)
            : undefined;
          const isStringValueContext =
            !location.isAtPropertyKey && valueNode?.type === 'string';

          const range = getCompletionFilterRange(
            text,
            completionContext.pos,
            location,
            valueNode
          );

          const view = completionContext.view;
          if (view && refactorCompletionArmed.get(view)) {
            refactorCompletionArmed.set(view, false);
            const refactorContext = getRefactorContext(
              text,
              view.state.selection.main.head,
              context.mode
            );
            if (refactorContext) {
              // Keep the completion UI anchored at the caret line.
              // The actual refactor actions rewrite the whole document,
              // so `from/to` here only controls dropdown placement.
              const anchor = completionContext.pos;
              return {
                from: anchor,
                to: anchor,
                filter: false,
                options: _toRefactorCompletions(refactorContext.actions),
              };
            }
          }

          const options = dedupeCompletions(
            location.isAtPropertyKey
              ? getPropertySuggestions(
                  text,
                  context,
                  location.path,
                  completionContext.pos,
                  location.isAtPropertyKey
                )
              : getValueSuggestions(
                  text,
                  context,
                  location.path,
                  isStringValueContext
                )
          );

          if (options.length === 0) {
            return null;
          }

          return {
            from: range.from,
            to: range.to,
            filter: true,
            options,
          };
        },
      ],
    }),
    completionNavigationKeymap,
    keymap.of(completionKeymap),
    // Backspace/delete often does not re-trigger `activateOnTyping`; reopen
    // completions whenever we are editing a string that has value suggestions.
    _createAutocompleteOpenWhenValueSuggestionsAfterEditExtension(context),
    buildCodeMirrorRefactorLightbulbExtension(context),
    ...(enableHoverExtension ? [_createHoverExtension(context)] : []),
    ...(enableHintsExtension ? [_createHintsExtension(context)] : []),
  ];
}

export function buildCodeMirrorStandaloneDebugExtensions(): Extension[] {
  const rootKeys = ['execution', 'action', 'scope'] as const;
  return [
    autocompletion({
      activateOnTyping: true,
      override: [
        (completionContext) => {
          const text = completionContext.state.doc.toString();
          const location = getLocation(text, completionContext.pos);
          const tree = parseTree(text);
          const valueNode = tree
            ? findNodeAtLocation(tree, location.path)
            : undefined;
          const isStringValueContext =
            !location.isAtPropertyKey && valueNode?.type === 'string';
          const range = getCompletionFilterRange(
            text,
            completionContext.pos,
            location,
            valueNode
          );

          if (location.isAtPropertyKey) {
            return {
              from: range.from,
              to: range.to,
              options: rootKeys.map((key) => ({
                label: key,
                type: 'property',
                apply: (
                  view: EditorView,
                  completion: Completion,
                  from: number,
                  to: number
                ) => {
                  const insert = `"${key}"`;
                  view.dispatch({
                    ...insertCompletionText(view.state, insert, from, to),
                    annotations: pickedCompletion.of(completion),
                  });
                },
              })),
            };
          }

          const path = location.path;
          let values: string[] = [];
          if (path[path.length - 1] === 'execution') {
            values = ['server', 'sdk'];
          } else if (
            path.length >= 2 &&
            path[path.length - 2] === 'action' &&
            path[path.length - 1] === 'decision'
          ) {
            values = ['allow', 'deny'];
          } else if (
            path.length >= 3 &&
            path[path.length - 3] === 'scope' &&
            path[path.length - 2] === 'stages' &&
            typeof path[path.length - 1] === 'number'
          ) {
            values = ['pre', 'post'];
          }

          if (values.length === 0) return null;
          return {
            from: range.from,
            to: range.to,
            filter: true,
            options: values.map((value) => ({
              label: value,
              type: 'enum',
              info: `Enum value: ${value}`,
              apply: (
                view: EditorView,
                completion: Completion,
                from: number,
                to: number
              ) => {
                const insert = isStringValueContext
                  ? value
                  : JSON.stringify(value);
                view.dispatch({
                  ...insertCompletionText(view.state, insert, from, to),
                  annotations: pickedCompletion.of(completion),
                });
              },
            })),
          };
        },
      ],
    }),
    keymap.of(completionKeymap),
    // completionNavigationKeymap,
  ];
}

export function triggerRefactorActionsDropdown(
  view: EditorView,
  mode: JsonEditorCodeMirrorContext['mode']
): boolean {
  const text = view.state.doc.toString();
  const offset = view.state.selection.main.head;
  const refactorContext = getRefactorContext(text, offset, mode);
  if (!refactorContext) return false;
  refactorCompletionArmed.set(view, true);
  startCompletion(view);
  return true;
}

export function buildCodeMirrorRefactorLightbulbExtension(
  context: JsonEditorCodeMirrorContext
): Extension {
  const marker = new LightbulbGutterMarker();
  return gutter({
    class: 'cm-refactor-lightbulb-gutter',
    initialSpacer: () => marker,
    markers(view) {
      const text = view.state.doc.toString();
      const offset = view.state.selection.main.head;
      const refactorContext = getRefactorContext(text, offset, context.mode);
      const builder = new RangeSetBuilder<GutterMarker>();
      if (refactorContext) {
        const line = view.state.doc.lineAt(offset);
        builder.add(line.from, line.from, marker);
      }
      return builder.finish();
    },
    domEventHandlers: {
      mousedown(view, _line) {
        const text = view.state.doc.toString();
        const offset = view.state.selection.main.head;
        const refactorContext = getRefactorContext(text, offset, context.mode);
        if (!refactorContext) return false;
        // Don't move the caret (keep bulb aligned with the user's caret line).
        window.setTimeout(() => {
          triggerRefactorActionsDropdown(view, context.mode);
        }, 0);
        return true;
      },
    },
  });
}

export function getCodeMirrorCompletionItems(
  text: string,
  position: number,
  context: JsonEditorCodeMirrorContext
): Array<{ label: string; detail?: string }> {
  const location = getLocation(text, position);
  const tree = parseTree(text);
  const valueNode = tree ? findNodeAtLocation(tree, location.path) : undefined;
  const isStringValueContext =
    !location.isAtPropertyKey && valueNode?.type === 'string';
  const options = location.isAtPropertyKey
    ? getPropertySuggestions(
        text,
        context,
        location.path,
        position,
        location.isAtPropertyKey
      )
    : getValueSuggestions(text, context, location.path, isStringValueContext);

  return dedupeCompletions(options).map((item) => ({
    label: item.label,
    detail: typeof item.detail === 'string' ? item.detail : undefined,
  }));
}

export function shouldTriggerEvaluatorNameCompletion(
  text: string,
  offset: number
): boolean {
  const location = getLocation(text, offset);
  if (!isEvaluatorNameLocation(location.path)) {
    return false;
  }

  const tree = parseTree(text);
  if (!tree) return true;
  const node = findNodeAtLocation(tree, location.path);
  if (!node) return true;

  if (node.type === 'string' && typeof node.value === 'string') {
    return node.value.trim().length === 0;
  }

  return false;
}
