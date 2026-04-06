import {
  type Extension,
  type Range,
  StateEffect,
  StateField,
} from '@codemirror/state';
import {
  Decoration,
  type DecorationSet,
  EditorView,
  ViewPlugin,
  type ViewUpdate,
  WidgetType,
} from '@codemirror/view';
import {
  findNodeAtLocation,
  type Node as JsonNode,
  parseTree,
} from 'jsonc-parser';

import type { ValidationErrorItem } from '@/core/api/types';

type InlineServerValidationPayload = {
  errors: ValidationErrorItem[];
};

export const setInlineServerValidationErrorsEffect =
  StateEffect.define<InlineServerValidationPayload>();

const inlineServerValidationField =
  StateField.define<InlineServerValidationPayload>({
    create: () => ({ errors: [] }),
    update(value, tr) {
      for (const effect of tr.effects) {
        if (effect.is(setInlineServerValidationErrorsEffect)) {
          return effect.value;
        }
      }
      return value;
    },
  });

const INLINE_VALIDATION_ERROR_THEME = EditorView.theme({
  '& .cm-inline-validation-error-key': {
    backgroundColor: 'rgba(255, 0, 0, 0.18)',
    borderBottom: '1px solid rgba(255, 0, 0, 0.55)',
  },
});

class InlineErrorWidget extends WidgetType {
  constructor(private readonly message: string) {
    super();
  }

  toDOM(): HTMLElement {
    const span = document.createElement('span');
    span.textContent = this.message;
    span.style.color = 'var(--mantine-color-red-6)';
    span.style.fontSize = '11px';
    span.style.marginLeft = '8px';
    span.style.padding = '2px 6px';
    span.style.borderRadius = '999px';
    span.style.background = 'rgba(255, 0, 0, 0.12)';
    span.style.whiteSpace = 'nowrap';
    span.style.pointerEvents = 'none';
    return span;
  }
}

type JsonPath = Array<string | number>;

function apiFieldToJsonPath(apiField: string): JsonPath | null {
  let field = apiField.trim();
  if (!field) return null;

  // Backend uses e.g. "data.action.decision".
  const dataPrefix = 'data.';
  if (field.startsWith(dataPrefix)) {
    field = field.slice(dataPrefix.length);
  }

  // Convert simple "foo[0]" patterns into path segments.
  const out: JsonPath = [];
  for (const segment of field.split('.')) {
    if (!segment) continue;
    const m = segment.match(/^([^\[]+)\[(\d+)\]$/);
    if (m) {
      out.push(m[1]);
      out.push(Number(m[2]));
      continue;
    }
    out.push(segment);
  }
  return out;
}

function findKeyAndValueRangesForJsonPath(
  tree: JsonNode | undefined,
  path: JsonPath
): {
  keyRange: { from: number; to: number } | null;
  valueRange: { from: number; to: number } | null;
} {
  if (!tree || path.length === 0) {
    return { keyRange: null, valueRange: null };
  }

  const valueNode = findNodeAtLocation(tree, path);
  const valueRange = valueNode
    ? { from: valueNode.offset, to: valueNode.offset + valueNode.length }
    : null;

  const keySegment = path[path.length - 1];
  let keyRange: { from: number; to: number } | null = null;

  // If the last segment is a string, try to locate the property key token.
  if (typeof keySegment === 'string') {
    const parentPath = path.slice(0, -1);
    const parentNode =
      parentPath.length > 0 ? findNodeAtLocation(tree, parentPath) : tree;

    if (parentNode?.type === 'object' && parentNode.children) {
      for (const prop of parentNode.children) {
        const propKey = prop.children?.[0];
        if (
          typeof propKey?.value === 'string' &&
          propKey.value === keySegment
        ) {
          keyRange = {
            from: propKey.offset,
            to: propKey.offset + propKey.length,
          };
          break;
        }
      }
    }
  }

  return { keyRange, valueRange };
}

function computeInlineValidationDecorations(
  view: EditorView,
  payload: InlineServerValidationPayload
): DecorationSet {
  const text = view.state.doc.toString();
  const tree = parseTree(text);
  if (!tree) return Decoration.none;

  const ranges: Range<Decoration>[] = [];
  for (const err of payload.errors) {
    if (!err.field) continue;
    const jsonPath = apiFieldToJsonPath(err.field);
    if (!jsonPath) continue;

    const { keyRange, valueRange } = findKeyAndValueRangesForJsonPath(
      tree,
      jsonPath
    );
    if (!keyRange && !valueRange) continue;

    const widget = new InlineErrorWidget(err.message);

    // Prefer highlighting the value so the user sees "what's wrong"
    // (e.g. highlight `"execution": "sdk"` rather than `"execution"`).
    // `markRange` can't be null here because we `continue` when both
    // `valueRange` and `keyRange` are missing.
    const markRange = (valueRange ?? keyRange)!;
    const widgetAfter = valueRange?.to ?? markRange.to;

    ranges.push(
      Decoration.mark({ class: 'cm-inline-validation-error-key' }).range(
        markRange.from,
        markRange.to
      )
    );
    // Always place the widget after the *value* so it renders after
    // `"execution": "sdk"` instead of between the key and value.
    ranges.push(Decoration.widget({ side: 1, widget }).range(widgetAfter));
  }

  return Decoration.set(ranges, true);
}

export function canRenderInlineServerValidationError(
  text: string,
  error: Pick<ValidationErrorItem, 'field'>
): boolean {
  if (!error.field) return false;

  const tree = parseTree(text);
  if (!tree) return false;

  const jsonPath = apiFieldToJsonPath(error.field);
  if (!jsonPath) return false;

  const { keyRange, valueRange } = findKeyAndValueRangesForJsonPath(
    tree,
    jsonPath
  );

  return Boolean(keyRange || valueRange);
}

export function buildCodeMirrorInlineServerValidationErrorsExtension(): Extension {
  return [
    INLINE_VALIDATION_ERROR_THEME,
    inlineServerValidationField,
    ViewPlugin.fromClass(
      class {
        decorations: DecorationSet = Decoration.none;
        private lastSignature = '';

        constructor(view: EditorView) {
          const payload = view.state.field(inlineServerValidationField);
          this.lastSignature = this.signature(payload);
          this.decorations = computeInlineValidationDecorations(view, payload);
        }

        update(update: ViewUpdate) {
          const payload = update.state.field(inlineServerValidationField);
          const sig = this.signature(payload);
          if (!update.docChanged && sig === this.lastSignature) return;
          this.lastSignature = sig;
          this.decorations = computeInlineValidationDecorations(
            update.view,
            payload
          );
        }

        private signature(payload: InlineServerValidationPayload): string {
          if (!payload.errors.length) return '';
          return payload.errors
            .map((e) => `${e.field ?? ''}|${e.code}|${e.message}`)
            .join('\n');
        }
      },
      {
        decorations: (plugin) => plugin.decorations,
      }
    ),
  ];
}
