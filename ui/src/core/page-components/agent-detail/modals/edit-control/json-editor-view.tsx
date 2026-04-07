import { ActionIcon, Box, Group, Text, Tooltip } from '@mantine/core';
import { useClipboard, useDebouncedValue } from '@mantine/hooks';
import {
  IconClipboardCheck,
  IconClipboardCopy,
  IconCode,
} from '@tabler/icons-react';
import { findNodeAtLocation, parseTree } from 'jsonc-parser';
import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  extractEvaluatorNames,
  findEvaluatorConfigEdit,
  findSteeringContextEdit,
  fixJsonCommas,
  getEmptyValueHints,
  getJsonEditorCompletionItems,
  setupJsonEditorLanguageSupport,
  TEMPLATE_DEFINITION_PREFIX,
} from '@/components/json-editor-monaco/json-editor-monaco-language';
import { isApiError } from '@/core/api/errors';
import { LabelWithTooltip } from '@/core/components/label-with-tooltip';

import { ApiErrorAlert } from './api-error-alert';
import type { JsonEditorViewProps } from './types';

const MonacoEditor = dynamic(
  async () => (await import('@monaco-editor/react')).default,
  { ssr: false }
);

type MonacoModule = typeof import('monaco-editor');
type MonacoEditorInstance =
  import('monaco-editor').editor.IStandaloneCodeEditor;

type JsonEditorTestElement = HTMLDivElement & {
  __getJsonEditorValue?: () => string;
  __getJsonEditorLanguageId?: () => string | null;
  __setJsonEditorValue?: (value: string) => void;
  __isJsonEditorReady?: () => boolean;
  __focusJsonEditorAt?: (lineNumber: number, column: number) => void;
  __triggerJsonEditorSuggest?: () => void;
  __getJsonEditorSuggestions?: (
    lineNumber: number,
    column: number
  ) => Array<{ label: string; detail?: string }>;
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_HEIGHT = 400;
const DEFAULT_VALIDATE_DEBOUNCE_MS = 500;
const DEFAULT_LABEL = 'Configuration (JSON)';
const DEFAULT_TOOLTIP = 'Raw JSON configuration';
const DEFAULT_TEST_ID = 'raw-json-textarea';
const DEFAULT_EDITOR_MODE = 'evaluator-config';
const HINT_DEBOUNCE_MS = 300;
const COMMA_FIX_DEBOUNCE_MS = 800;
const CURSOR_TRIGGER_DEBOUNCE_MS = 50;
const HINT_CSS_CLASS = 'json-editor-value-hint';
const VALIDATION_ERROR_CSS_CLASS = 'json-editor-validation-error';

// Inject validation error highlighting styles once.
if (typeof document !== 'undefined') {
  const id = 'json-editor-validation-error-styles';
  if (!document.getElementById(id)) {
    const style = document.createElement('style');
    style.id = id;
    style.textContent = `.${VALIDATION_ERROR_CSS_CLASS} { background-color: rgba(255, 0, 0, 0.15); border-bottom: 2px wavy rgba(255, 0, 0, 0.6); }`;
    document.head.appendChild(style);
  }
}

// Dynamic hint styles — each unique hint text gets a CSS class with ::after content.
// Monaco 0.55 doesn't support `after.content` in decorations, so we use
// `afterContentClassName` with CSS `::after` pseudo-elements instead.
let hintStyleEl: HTMLStyleElement | null = null;
let hintClassCounter = 0;
const hintClassMap = new Map<string, string>();

function getHintClassName(hintText: string): string {
  let cls = hintClassMap.get(hintText);
  if (cls) return cls;

  cls = `${HINT_CSS_CLASS}-${hintClassCounter++}`;
  hintClassMap.set(hintText, cls);

  if (typeof document !== 'undefined') {
    if (!hintStyleEl) {
      hintStyleEl = document.createElement('style');
      hintStyleEl.id = 'json-editor-hint-styles';
      document.head.appendChild(hintStyleEl);
    }
    const escaped = hintText.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    hintStyleEl.textContent += `.${cls}::after { content: "${escaped}"; color: var(--mantine-color-gray-5); font-style: italic; pointer-events: none; }\n`;
  }
  return cls;
}

const EDITOR_OPTIONS: import('monaco-editor').editor.IStandaloneEditorConstructionOptions =
  {
    automaticLayout: true,
    quickSuggestions: false,
    suggestOnTriggerCharacters: true,
    wordBasedSuggestions: 'off',
    suggest: {
      showWords: false,
      preview: true,
      showIcons: true,
      insertMode: 'replace',
    },
    snippetSuggestions: 'inline',
    acceptSuggestionOnEnter: 'off',
    fontFamily:
      'ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, monospace',
    fontSize: 12,
    formatOnPaste: true,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    tabSize: 2,
    insertSpaces: true,
    wordWrap: 'off',
    bracketPairColorization: { enabled: true },
    guides: { bracketPairs: true, indentation: true },
    stickyScroll: { enabled: true },
    padding: { top: 8, bottom: 8 },
    folding: true,
    showFoldingControls: 'mouseover',
    renderLineHighlight: 'line',
    cursorSmoothCaretAnimation: 'on',
    smoothScrolling: true,
  };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isSuggestWidgetVisible(editor: MonacoEditorInstance): boolean {
  return (
    editor
      .getDomNode()
      ?.querySelector('.suggest-widget')
      ?.classList.contains('visible') ?? false
  );
}

function replaceAllContent(
  editor: MonacoEditorInstance,
  newText: string,
  source: string
) {
  const model = editor.getModel();
  if (!model) return;
  editor.executeEdits(source, [
    { range: model.getFullModelRange(), text: newText },
  ]);
  const pos = editor.getPosition();
  if (pos && pos.lineNumber > model.getLineCount()) {
    editor.setPosition({ lineNumber: model.getLineCount(), column: 1 });
  }
}

function tryFormat(text: string): string | null {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return null;
  }
}

/** Check if the cursor is at a position where auto-triggering suggestions is useful. */
function shouldAutoTriggerSuggest(
  line: string | undefined,
  column: number,
  skipStringTrigger: boolean,
  hasSuggestions: () => boolean
): boolean {
  if (!line) return false;
  const beforeCursor = line.substring(0, column - 1);
  const afterCursor = line.substring(column - 1);

  // Blank / comma-only line — always trigger (even after Enter)
  if (/^\s*,?\s*$/.test(line)) return true;

  // Typing `"` at a property-key position (whitespace + optional comma + `"`)
  // should trigger property name suggestions immediately.
  if (/^\s*,?\s*"$/.test(beforeCursor) && !afterCursor.includes(':')) {
    return true;
  }

  // Don't trigger string suggestions after typing
  if (skipStringTrigger) return false;

  // Check if inside a string value (not a property key)
  const quotesBefore = beforeCursor.split('"').length - 1;
  const isInString = quotesBefore % 2 === 1 && /^[^"]*"/.test(afterCursor);
  if (!isInString) return false;
  if (/^\s*:/.test(afterCursor.replace(/^[^"]*"/, ''))) return false;

  const openIdx = beforeCursor.lastIndexOf('"');
  const closeIdx = afterCursor.indexOf('"');
  const contentLen =
    openIdx >= 0 && closeIdx >= 0
      ? beforeCursor.length - openIdx - 1 + closeIdx
      : 999;

  // Short strings: always trigger (browsing options)
  if (contentLen <= 2) return true;

  // Longer strings: trigger if our provider has suggestions (enum values,
  // evaluator names, selector paths). This covers all domain fields
  // including evaluator config enums (logic, match_on, mode, etc.)
  // without hardcoding field names.
  return hasSuggestions();
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const JsonEditorView = ({
  jsonText,
  handleJsonChange,
  jsonError,
  setJsonError,
  validationError,
  setValidationError,
  onValidateConfig,
  onValidationStatusChange,
  validateDebounceMs = DEFAULT_VALIDATE_DEBOUNCE_MS,
  height = DEFAULT_HEIGHT,
  label = DEFAULT_LABEL,
  tooltip = DEFAULT_TOOLTIP,
  helperText,
  testId = DEFAULT_TEST_ID,
  editorMode = DEFAULT_EDITOR_MODE,
  schema,
  evaluators,
  activeEvaluatorId,
  steps,
  templateParameterNames,
}: JsonEditorViewProps) => {
  const [isDarkMode, setIsDarkMode] = useState(false);
  const [debouncedJsonText] = useDebouncedValue(jsonText, validateDebounceMs);
  const [mounted, setMounted] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const editorRef = useRef<MonacoEditorInstance | null>(null);
  const monacoRef = useRef<MonacoModule | null>(null);
  const editorRootRef = useRef<JsonEditorTestElement | null>(null);
  const cleanupLanguageRef = useRef<(() => void) | null>(null);

  const definitionPrefix =
    editorMode === 'template' ? TEMPLATE_DEFINITION_PREFIX : undefined;

  const modelUri = useMemo(
    () => `inmemory://agent-control/${testId}.json`,
    [testId]
  );
  const autocompleteContext = useMemo(
    () => ({
      mode: editorMode,
      modelUri,
      schema,
      evaluators,
      activeEvaluatorId,
      steps,
      definitionPrefix,
      templateParameterNames,
    }),
    [
      activeEvaluatorId,
      definitionPrefix,
      editorMode,
      evaluators,
      modelUri,
      schema,
      steps,
      templateParameterNames,
    ]
  );

  const clipboard = useClipboard({ timeout: 1500 });

  // --- Dark mode ---
  useEffect(() => {
    const detect = () =>
      setIsDarkMode(
        document.documentElement.getAttribute('data-mantine-color-scheme') ===
          'dark'
      );
    detect();
    const obs = new MutationObserver(detect);
    obs.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-mantine-color-scheme'],
    });
    return () => obs.disconnect();
  }, []);

  // --- Toolbar ---
  const formatDocument = useCallback(() => {
    const editor = editorRef.current;
    if (!editor) return;
    const commaFixed = fixJsonCommas(editor.getValue());
    const formatted = tryFormat(commaFixed);
    if (formatted && formatted !== editor.getValue()) {
      replaceAllContent(editor, formatted, 'format');
      handleJsonChange(formatted);
    } else if (commaFixed !== editor.getValue()) {
      replaceAllContent(editor, commaFixed, 'comma-fix');
      handleJsonChange(commaFixed);
    }
  }, [handleJsonChange]);

  const copyToClipboard = useCallback(() => {
    clipboard.copy(editorRef.current?.getValue() ?? jsonText);
  }, [clipboard, jsonText]);

  // --- Mount ---
  const handleEditorMount = useCallback(
    (editor: MonacoEditorInstance, monaco: MonacoModule) => {
      editorRef.current = editor;
      monacoRef.current = monaco;
      setMounted(true);
    },
    []
  );

  // --- Language support ---
  useEffect(() => {
    if (!mounted || !monacoRef.current) return;
    cleanupLanguageRef.current?.();
    cleanupLanguageRef.current = setupJsonEditorLanguageSupport(
      monacoRef.current,
      autocompleteContext
    );
    return () => {
      cleanupLanguageRef.current?.();
      cleanupLanguageRef.current = null;
    };
  }, [mounted, autocompleteContext]);

  // --- Unified content-change listener ---
  useEffect(() => {
    const editor = editorRef.current;
    const monaco = monacoRef.current;
    if (!editor || !monaco || !mounted) return;

    let decorationIds: string[] = [];
    const updateHints = () => {
      const model = editor.getModel();
      if (!model) return;
      try {
        decorationIds = editor.deltaDecorations(
          decorationIds,
          getEmptyValueHints(monaco, model, autocompleteContext).map((h) => ({
            range: h.range,
            options: {
              afterContentClassName: getHintClassName(h.hint),
            },
          }))
        );
      } catch {
        decorationIds = editor.deltaDecorations(decorationIds, []);
      }
    };
    updateHints();

    let prevEvalNames = extractEvaluatorNames(
      editor.getValue(),
      definitionPrefix
    );
    let prevDecision: string | null = null;
    try {
      const initTree = parseTree(editor.getValue());
      const initSubtree =
        definitionPrefix && initTree
          ? findNodeAtLocation(initTree, definitionPrefix)
          : initTree;
      const decisionNode = initSubtree
        ? findNodeAtLocation(initSubtree, ['action', 'decision'])
        : null;
      prevDecision =
        typeof decisionNode?.value === 'string' ? decisionNode.value : null;
    } catch {
      /* ignore */
    }
    let isProgrammaticEdit = false;
    let hintTimer: number | null = null;
    let commaTimer: number | null = null;

    const applyEdit = (
      edit: { offset: number; length: number; newText: string },
      source: string
    ) => {
      const model = editor.getModel();
      if (!model) return;
      const start = model.getPositionAt(edit.offset);
      const end = model.getPositionAt(edit.offset + edit.length);
      // NOTE: This async boundary (queueMicrotask) means the auto-edit
      // creates a separate undo group from the user's keystroke. This breaks
      // redo after undo when auto-edits fire (e.g. evaluator config fill).
      // Synchronous alternatives (model.applyEdits) crash Monaco's worker.
      // This is a known Monaco limitation — undo still works correctly.
      queueMicrotask(() => {
        isProgrammaticEdit = true;
        editor.executeEdits(source, [
          {
            range: {
              startLineNumber: start.lineNumber,
              startColumn: start.column,
              endLineNumber: end.lineNumber,
              endColumn: end.column,
            },
            text: edit.newText,
          },
        ]);
        const formatted = tryFormat(editor.getValue());
        if (formatted && formatted !== editor.getValue()) {
          replaceAllContent(editor, formatted, 'reformat');
          handleJsonChange(formatted);
        } else {
          handleJsonChange(editor.getValue());
        }
      });
    };

    const disposable = editor.onDidChangeModelContent((_e) => {
      if (isProgrammaticEdit) {
        isProgrammaticEdit = false;
        return;
      }

      const text = editor.getValue();

      // No auto-reformat here — code actions produce formatted JSON by replacing
      // the full document (see buildNodeTransformAction). Auto-reformatting would
      // create a second undo entry that breaks Ctrl+Z.

      // Debounced hints
      if (hintTimer) window.clearTimeout(hintTimer);
      hintTimer = window.setTimeout(updateHints, HINT_DEBOUNCE_MS);

      // Debounced comma fix (only on blur, only if result is valid)
      if (commaTimer) window.clearTimeout(commaTimer);
      commaTimer = window.setTimeout(() => {
        if (isSuggestWidgetVisible(editor) || editor.hasTextFocus()) return;
        const current = editor.getValue();
        const fixed = fixJsonCommas(current);
        if (fixed !== current && tryFormat(fixed)) {
          isProgrammaticEdit = true;
          replaceAllContent(editor, fixed, 'auto-comma-fix');
          handleJsonChange(fixed);
        }
      }, COMMA_FIX_DEBOUNCE_MS);

      // Immediate: dependent field updates (control & template modes)
      if (editorMode === 'control' || editorMode === 'template') {
        const evalEdit = findEvaluatorConfigEdit(
          text,
          prevEvalNames,
          evaluators,
          definitionPrefix
        );
        prevEvalNames = extractEvaluatorNames(text, definitionPrefix);
        if (evalEdit) {
          applyEdit(evalEdit, 'evaluator-config-update');
          return;
        }

        const steerEdit = findSteeringContextEdit(
          text,
          prevDecision,
          definitionPrefix
        );
        try {
          const steerTree = parseTree(text);
          const steerSubtree =
            definitionPrefix && steerTree
              ? findNodeAtLocation(steerTree, definitionPrefix)
              : steerTree;
          const decNode = steerSubtree
            ? findNodeAtLocation(steerSubtree, ['action', 'decision'])
            : null;
          prevDecision =
            typeof decNode?.value === 'string' ? decNode.value : null;
        } catch {
          /* ignore */
        }
        if (steerEdit) {
          applyEdit(steerEdit, 'steering-context-update');
        }
      }
    });

    return () => {
      if (hintTimer) window.clearTimeout(hintTimer);
      if (commaTimer) window.clearTimeout(commaTimer);
      disposable.dispose();
      editor.deltaDecorations(decorationIds, []);
    };
  }, [
    mounted,
    autocompleteContext,
    definitionPrefix,
    editorMode,
    evaluators,
    handleJsonChange,
  ]);

  // --- Cursor auto-trigger ---
  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || !mounted) return;

    // Track content changes to suppress string-value auto-trigger after typing.
    // Blank line triggers still fire (Enter creates a new line → want suggestions).
    let contentJustChanged = false;
    const contentDisposable = editor.onDidChangeModelContent((e) => {
      // Only flag as "typing" for small single-char edits, not large replacements
      // (setValue, code actions, reformat). This prevents suppressing auto-trigger
      // after programmatic content changes.
      const isSmallEdit =
        e.changes.length === 1 &&
        e.changes[0].text.length <= 2 &&
        !e.changes[0].text.includes('\n');
      contentJustChanged = isSmallEdit;
    });

    let timeout: number | null = null;
    const disposable = editor.onDidChangeCursorPosition(() => {
      if (timeout) window.clearTimeout(timeout);
      timeout = window.setTimeout(() => {
        try {
          const pos = editor.getPosition();
          const model = editor.getModel();
          if (!pos || !model) return;
          if (pos.lineNumber < 1 || pos.lineNumber > model.getLineCount())
            return;

          const wasTyping = contentJustChanged;
          contentJustChanged = false;

          const trigger = shouldAutoTriggerSuggest(
            model.getLineContent(pos.lineNumber),
            pos.column,
            wasTyping,
            () =>
              monacoRef.current
                ? getJsonEditorCompletionItems(
                    monacoRef.current,
                    model,
                    pos,
                    autocompleteContext
                  ).length > 0
                : false
          );
          if (trigger) {
            editor.trigger('cursor', 'editor.action.triggerSuggest', {});
          }
        } catch {
          // Ignore — stale cursor during undo
        }
      }, CURSOR_TRIGGER_DEBOUNCE_MS);
    });

    return () => {
      if (timeout) window.clearTimeout(timeout);
      disposable.dispose();
      contentDisposable.dispose();
    };
  }, [mounted, autocompleteContext]);

  // --- Test harness ---
  useEffect(() => {
    const root = editorRootRef.current;
    if (!root) return;
    root.__getJsonEditorValue = () => editorRef.current?.getValue() ?? '';
    root.__getJsonEditorLanguageId = () =>
      editorRef.current?.getModel()?.getLanguageId() ?? null;
    root.__isJsonEditorReady = () =>
      Boolean(editorRef.current && monacoRef.current);
    root.__focusJsonEditorAt = (l, c) => {
      if (!editorRef.current || !monacoRef.current) return;
      editorRef.current.setPosition(new monacoRef.current.Position(l, c));
      editorRef.current.focus();
    };
    root.__setJsonEditorValue = (v) => {
      editorRef.current?.setValue(v);
      editorRef.current?.focus();
      handleJsonChange(v);
    };
    root.__triggerJsonEditorSuggest = () => {
      editorRef.current?.focus();
      editorRef.current?.trigger(
        'keyboard',
        'editor.action.triggerSuggest',
        {}
      );
    };
    root.__getJsonEditorSuggestions = (l, c) => {
      if (!editorRef.current || !monacoRef.current) return [];
      const model = editorRef.current.getModel();
      if (!model) return [];
      return getJsonEditorCompletionItems(
        monacoRef.current,
        model,
        new monacoRef.current.Position(l, c),
        autocompleteContext
      ).map((item) => ({
        label: typeof item.label === 'string' ? item.label : item.label.label,
        detail: typeof item.detail === 'string' ? item.detail : undefined,
      }));
    };
    return () => {
      delete root.__getJsonEditorValue;
      delete root.__getJsonEditorLanguageId;
      delete root.__isJsonEditorReady;
      delete root.__focusJsonEditorAt;
      delete root.__setJsonEditorValue;
      delete root.__triggerJsonEditorSuggest;
      delete root.__getJsonEditorSuggestions;
    };
  }, [autocompleteContext, handleJsonChange]);

  // --- Validation ---
  useEffect(() => {
    if (!onValidateConfig) return;
    if (!debouncedJsonText) {
      setJsonError?.(null);
      setValidationError?.(null);
      onValidationStatusChange?.('idle');
      return;
    }

    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(debouncedJsonText) as Record<string, unknown>;
    } catch {
      setJsonError?.('Invalid JSON');
      setValidationError?.(null);
      onValidationStatusChange?.('invalid');
      return;
    }

    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    setJsonError?.(null);
    onValidationStatusChange?.('validating');
    onValidateConfig(parsed, { signal: controller.signal })
      .then(() => {
        setValidationError?.(null);
        onValidationStatusChange?.('valid');
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        if (isApiError(error)) {
          setValidationError?.(error.problemDetail);
          onValidationStatusChange?.('invalid');
        } else {
          setJsonError?.('Validation failed.');
          setValidationError?.(null);
          onValidationStatusChange?.('invalid');
        }
      });
    return () => controller.abort();
  }, [
    debouncedJsonText,
    onValidateConfig,
    onValidationStatusChange,
    setJsonError,
    setValidationError,
  ]);

  // --- Inline validation error decorations ---
  const validationDecorationIds = useRef<string[]>([]);
  useEffect(() => {
    const editor = editorRef.current;
    const monaco = monacoRef.current;
    if (!editor || !monaco) return;

    if (!validationError?.errors?.length) {
      validationDecorationIds.current = editor.deltaDecorations(
        validationDecorationIds.current,
        []
      );
      return;
    }

    const text = editor.getValue();
    const tree = parseTree(text);
    if (!tree) return;

    const model = editor.getModel();
    if (!model) return;

    const decorations: import('monaco-editor').editor.IModelDeltaDecoration[] =
      [];
    for (const err of validationError.errors) {
      if (!err.field) continue;
      // Convert API field path (e.g. "data.action.decision") to JSON path
      let field = err.field.trim();
      if (field.startsWith('data.')) field = field.slice(5);
      const segments: Array<string | number> = [];
      for (const seg of field.split('.')) {
        if (!seg) continue;
        const m = seg.match(/^([^[]+)\[(\d+)]$/);
        if (m) {
          segments.push(m[1]);
          segments.push(Number(m[2]));
        } else {
          segments.push(seg);
        }
      }
      if (segments.length === 0) continue;

      // Find the value node at this path
      const valueNode = findNodeAtLocation(tree, segments);
      if (!valueNode) continue;

      const startPos = model.getPositionAt(valueNode.offset);
      const endPos = model.getPositionAt(valueNode.offset + valueNode.length);
      decorations.push({
        range: new monaco.Range(
          startPos.lineNumber,
          startPos.column,
          endPos.lineNumber,
          endPos.column
        ),
        options: {
          inlineClassName: 'json-editor-validation-error',
          hoverMessage: { value: err.message },
          overviewRuler: {
            color: 'rgba(255, 0, 0, 0.7)',
            position: monaco.editor.OverviewRulerLane.Right,
          },
        },
      });
    }

    validationDecorationIds.current = editor.deltaDecorations(
      validationDecorationIds.current,
      decorations
    );
  }, [validationError]);

  // --- Render ---
  return (
    <Box>
      <Group justify="space-between" align="center" gap="xs">
        <LabelWithTooltip label={label} tooltip={tooltip} />
        <Group gap={4}>
          <Tooltip label="Format (Shift+Alt+F)" openDelay={400}>
            <ActionIcon
              variant="subtle"
              color="gray"
              size="sm"
              onClick={formatDocument}
              aria-label="Format document"
            >
              <IconCode size={14} />
            </ActionIcon>
          </Tooltip>
          <Tooltip
            label={clipboard.copied ? 'Copied!' : 'Copy JSON'}
            openDelay={clipboard.copied ? 0 : 400}
          >
            <ActionIcon
              variant="subtle"
              color={clipboard.copied ? 'teal' : 'gray'}
              size="sm"
              onClick={copyToClipboard}
              aria-label="Copy JSON to clipboard"
            >
              {clipboard.copied ? (
                <IconClipboardCheck size={14} />
              ) : (
                <IconClipboardCopy size={14} />
              )}
            </ActionIcon>
          </Tooltip>
        </Group>
      </Group>
      {validationError ? (
        <Box mt="xs" mb="xs">
          <ApiErrorAlert error={validationError} unmappedErrors={[]} />
        </Box>
      ) : null}
      <Box
        ref={editorRootRef}
        mt={4}
        data-testid={testId}
        style={{
          position: 'relative',
          border: `1px solid ${
            jsonError
              ? 'var(--mantine-color-red-6)'
              : 'var(--mantine-color-gray-4)'
          }`,
          borderRadius: 8,
        }}
      >
        <Box>
          <MonacoEditor
            height={height}
            defaultLanguage="json"
            theme={isDarkMode ? 'vs-dark' : 'vs'}
            path={modelUri}
            value={jsonText}
            onChange={(v) => handleJsonChange(v ?? '')}
            onMount={handleEditorMount}
            options={EDITOR_OPTIONS}
          />
        </Box>
      </Box>
      {jsonError ? (
        <Text size="xs" c="red" mt="xs">
          {jsonError}
        </Text>
      ) : null}
      {helperText ? (
        <Text size="xs" c="dimmed" mt="xs">
          {helperText}
        </Text>
      ) : null}
    </Box>
  );
};
