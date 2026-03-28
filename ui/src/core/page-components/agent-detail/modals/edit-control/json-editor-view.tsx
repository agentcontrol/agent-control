import { ActionIcon, Box, Group, Text, Tooltip } from '@mantine/core';
import { useClipboard, useDebouncedValue } from '@mantine/hooks';
import {
  IconClipboardCheck,
  IconClipboardCopy,
  IconCode,
} from '@tabler/icons-react';
import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { isApiError } from '@/core/api/errors';
import { LabelWithTooltip } from '@/core/components/label-with-tooltip';

import { ApiErrorAlert } from './api-error-alert';
import {
  extractEvaluatorNames,
  findEvaluatorConfigEdit,
  findSteeringContextEdit,
  fixJsonCommas,
  getEmptyValueHints,
  getJsonEditorCompletionItems,
  setupJsonEditorLanguageSupport,
} from './json-editor-language';
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

// Injected once — never removed. Shared across all editor instances.
if (typeof document !== 'undefined') {
  const id = 'json-editor-hint-style';
  if (!document.getElementById(id)) {
    const style = document.createElement('style');
    style.id = id;
    style.textContent = `.${HINT_CSS_CLASS} { color: var(--mantine-color-gray-5); font-style: italic; }`;
    document.head.appendChild(style);
  }
}

const EDITOR_OPTIONS: import('monaco-editor').editor.IStandaloneEditorConstructionOptions =
  {
    automaticLayout: true,
    quickSuggestions: { other: true, strings: true, comments: false },
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
  hasDomainSuggestions: () => boolean
): boolean {
  if (!line) return false;
  const beforeCursor = line.substring(0, column - 1);
  const afterCursor = line.substring(column - 1);

  // Blank / comma-only line — likely inside an object needing a property
  if (/^\s*,?\s*$/.test(line)) return true;

  // Check if inside a string
  const quotesBefore = beforeCursor.split('"').length - 1;
  const isInString = quotesBefore % 2 === 1 && /^[^"]*"/.test(afterCursor);
  if (!isInString) return false;

  // Don't trigger on property keys (have ":" after closing quote)
  if (/^\s*:/.test(afterCursor.replace(/^[^"]*"/, ''))) return false;

  // Short strings: always trigger
  const openIdx = beforeCursor.lastIndexOf('"');
  const closeIdx = afterCursor.indexOf('"');
  const contentLen =
    openIdx >= 0 && closeIdx >= 0
      ? beforeCursor.length - openIdx - 1 + closeIdx
      : 999;
  if (contentLen <= 2) return true;

  // Longer strings: only if we have domain-specific suggestions
  return hasDomainSuggestions();
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
}: JsonEditorViewProps) => {
  const [isDarkMode, setIsDarkMode] = useState(false);
  const [debouncedJsonText] = useDebouncedValue(jsonText, validateDebounceMs);
  const [mounted, setMounted] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const editorRef = useRef<MonacoEditorInstance | null>(null);
  const monacoRef = useRef<MonacoModule | null>(null);
  const editorRootRef = useRef<JsonEditorTestElement | null>(null);
  const cleanupLanguageRef = useRef<(() => void) | null>(null);

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
    }),
    [activeEvaluatorId, editorMode, evaluators, modelUri, schema, steps]
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

    const decorations = editor.createDecorationsCollection();
    const updateHints = () => {
      const model = editor.getModel();
      if (!model) return;
      try {
        decorations.set(
          getEmptyValueHints(monaco, model, autocompleteContext).map((h) => ({
            range: h.range,
            options: {
              after: {
                content: h.hint,
                inlineClassName: HINT_CSS_CLASS,
                cursorStops: monaco.editor.InjectedTextCursorStops.None,
              },
            },
          }))
        );
      } catch {
        decorations.clear();
      }
    };
    updateHints();

    let prevEvalNames = extractEvaluatorNames(editor.getValue());
    let prevDecision: string | null = null;
    try {
      prevDecision = JSON.parse(editor.getValue())?.action?.decision ?? null;
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
        if (formatted) {
          replaceAllContent(editor, formatted, 'reformat');
          handleJsonChange(formatted);
        } else {
          handleJsonChange(editor.getValue());
        }
      });
    };

    const disposable = editor.onDidChangeModelContent((e) => {
      if (isProgrammaticEdit) {
        isProgrammaticEdit = false;
        return;
      }

      const text = editor.getValue();

      // Immediate reformat for multi-line edits (e.g., code actions like "Wrap in AND").
      // Only triggers when a single change spans multiple lines — normal typing
      // is single-line and won't match, avoiding cursor-jump issues.
      const isMultiLineEdit =
        !e.isUndoing &&
        !e.isRedoing &&
        e.changes.length === 1 &&
        (e.changes[0].text.includes('\n') ||
          e.changes[0].range.endLineNumber >
            e.changes[0].range.startLineNumber);
      if (isMultiLineEdit) {
        const formatted = tryFormat(text);
        if (formatted && formatted !== text) {
          isProgrammaticEdit = true;
          replaceAllContent(editor, formatted, 'auto-reformat');
          handleJsonChange(formatted);
          return;
        }
      }

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

      // Immediate: dependent field updates (control mode only)
      if (editorMode === 'control') {
        const evalEdit = findEvaluatorConfigEdit(
          text,
          prevEvalNames,
          evaluators
        );
        prevEvalNames = extractEvaluatorNames(text);
        if (evalEdit) {
          applyEdit(evalEdit, 'evaluator-config-update');
          return;
        }

        const steerEdit = findSteeringContextEdit(text, prevDecision);
        try {
          prevDecision = JSON.parse(text)?.action?.decision ?? null;
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
      decorations.clear();
    };
  }, [mounted, autocompleteContext, editorMode, evaluators, handleJsonChange]);

  // --- Cursor auto-trigger ---
  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || !mounted) return;

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

          const trigger = shouldAutoTriggerSuggest(
            model.getLineContent(pos.lineNumber),
            pos.column,
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
        <Box style={{ borderRadius: 8, overflow: 'clip' }}>
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
      {validationError ? (
        <Box mt="sm">
          <ApiErrorAlert error={validationError} unmappedErrors={[]} />
        </Box>
      ) : null}
    </Box>
  );
};
