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

const DEFAULT_HEIGHT = 400;
const DEFAULT_VALIDATE_DEBOUNCE_MS = 500;
const DEFAULT_LABEL = 'Configuration (JSON)';
const DEFAULT_TOOLTIP = 'Raw JSON configuration';
const DEFAULT_TEST_ID = 'raw-json-textarea';
const DEFAULT_EDITOR_MODE = 'evaluator-config';
const HINT_DEBOUNCE_MS = 300;
const COMMA_FIX_DEBOUNCE_MS = 800;

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

/** Replace all editor content via executeEdits (preserves undo stack). */
function replaceAllContent(
  editor: MonacoEditorInstance,
  newText: string,
  source: string
) {
  const model = editor.getModel();
  if (!model) return;
  const fullRange = model.getFullModelRange();
  editor.executeEdits(source, [
    { range: fullRange, text: newText, forceMoveMarkers: true },
  ]);
}

function reformatIfValid(
  editor: MonacoEditorInstance,
  handleJsonChange: (text: string) => void
) {
  try {
    const formatted = JSON.stringify(JSON.parse(editor.getValue()), null, 2);
    replaceAllContent(editor, formatted, 'reformat');
    handleJsonChange(formatted);
  } catch {
    handleJsonChange(editor.getValue());
  }
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

  // ---------------------------------------------------------------------------
  // Dark mode — read from outer MantineProvider DOM attribute
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const detect = () =>
      setIsDarkMode(
        document.documentElement.getAttribute('data-mantine-color-scheme') ===
          'dark'
      );
    detect();
    const observer = new MutationObserver(detect);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-mantine-color-scheme'],
    });
    return () => observer.disconnect();
  }, []);

  // ---------------------------------------------------------------------------
  // Toolbar actions
  // ---------------------------------------------------------------------------
  const formatDocument = useCallback(() => {
    const editor = editorRef.current;
    if (!editor) return;
    const text = editor.getValue();
    const commaFixed = fixJsonCommas(text);
    try {
      const formatted = JSON.stringify(JSON.parse(commaFixed), null, 2);
      if (formatted !== text) {
        replaceAllContent(editor, formatted, 'format');
        handleJsonChange(formatted);
      }
    } catch {
      if (commaFixed !== text) {
        replaceAllContent(editor, commaFixed, 'comma-fix');
        handleJsonChange(commaFixed);
      }
      editor.getAction('editor.action.formatDocument')?.run();
    }
  }, [handleJsonChange]);

  const copyToClipboard = useCallback(() => {
    clipboard.copy(editorRef.current?.getValue() ?? jsonText);
  }, [clipboard, jsonText]);

  // ---------------------------------------------------------------------------
  // Editor mount
  // ---------------------------------------------------------------------------
  const handleEditorMount = useCallback(
    (editor: MonacoEditorInstance, monaco: MonacoModule) => {
      editorRef.current = editor;
      monacoRef.current = monaco;
      setMounted(true);
    },
    []
  );

  // ---------------------------------------------------------------------------
  // Language support (completion provider + schema diagnostics)
  // ---------------------------------------------------------------------------
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

  // ---------------------------------------------------------------------------
  // Unified content-change listener
  //
  // One listener handles all content-change reactions:
  //   1. Inline hint decorations (debounced 300ms)
  //   2. Comma auto-fix (debounced 800ms, skipped during suggest / programmatic edits)
  //   3. Dependent field updates — evaluator config + steering_context (immediate)
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const editor = editorRef.current;
    const monaco = monacoRef.current;
    if (!editor || !monaco || !mounted) return;

    // --- Hint decorations setup ---
    const hintClassName = 'json-editor-value-hint';
    const styleEl = document.createElement('style');
    styleEl.textContent = `.${hintClassName} { color: var(--mantine-color-gray-5); font-style: italic; }`;
    document.head.appendChild(styleEl);
    const decorations = editor.createDecorationsCollection();

    const updateHints = () => {
      const model = editor.getModel();
      if (!model) return;
      try {
        const hints = getEmptyValueHints(monaco, model, autocompleteContext);
        decorations.set(
          hints.map((h) => ({
            range: h.range,
            options: {
              after: {
                content: h.hint,
                inlineClassName: hintClassName,
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

    // --- Dependent-field tracking (evaluator name + decision) ---
    let prevEvalNames = extractEvaluatorNames(editor.getValue());
    let prevDecision: string | null = null;
    try {
      prevDecision = JSON.parse(editor.getValue())?.action?.decision ?? null;
    } catch {
      /* ignore */
    }
    // Programmatic edits (config update, comma fix, reformat) set this flag
    // so subsequent content-change events from setValue don't re-trigger fixes.
    let isProgrammaticEdit = false;

    const applyEditAndReformat = (
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
        reformatIfValid(editor, handleJsonChange);
      });
    };

    // --- Timers ---
    let hintTimer: number | null = null;
    let commaTimer: number | null = null;

    const disposable = editor.onDidChangeModelContent(() => {
      // Skip all reactive logic for changes we made ourselves
      if (isProgrammaticEdit) {
        isProgrammaticEdit = false;
        return;
      }

      const text = editor.getValue();

      // 1. Debounced hint update
      if (hintTimer) window.clearTimeout(hintTimer);
      hintTimer = window.setTimeout(updateHints, HINT_DEBOUNCE_MS);

      // 2. Debounced comma auto-fix + reformat
      if (commaTimer) window.clearTimeout(commaTimer);
      commaTimer = window.setTimeout(() => {
        if (isSuggestWidgetVisible(editor)) return;
        const current = editor.getValue();
        const commaFixed = fixJsonCommas(current);

        // Only apply changes if the result is valid JSON.
        // Don't touch broken JSON mid-edit — comma insertion can corrupt it.
        try {
          const formatted = JSON.stringify(JSON.parse(commaFixed), null, 2);
          if (formatted !== current) {
            isProgrammaticEdit = true;
            replaceAllContent(editor, formatted, 'auto-reformat');
            handleJsonChange(formatted);
          }
        } catch {
          // JSON is invalid — leave it alone, user is still editing
        }
      }, COMMA_FIX_DEBOUNCE_MS);

      // 3. Immediate: dependent field updates (control mode only)
      if (editorMode === 'control') {
        const evalEdit = findEvaluatorConfigEdit(
          text,
          prevEvalNames,
          evaluators
        );
        prevEvalNames = extractEvaluatorNames(text);
        if (evalEdit) {
          applyEditAndReformat(evalEdit, 'evaluator-config-update');
          return;
        }

        const steerEdit = findSteeringContextEdit(text, prevDecision);
        try {
          prevDecision = JSON.parse(text)?.action?.decision ?? null;
        } catch {
          /* ignore */
        }
        if (steerEdit) {
          applyEditAndReformat(steerEdit, 'steering-context-update');
        }
      }
    });

    return () => {
      if (hintTimer) window.clearTimeout(hintTimer);
      if (commaTimer) window.clearTimeout(commaTimer);
      disposable.dispose();
      decorations.clear();
      styleEl.remove();
    };
  }, [mounted, autocompleteContext, editorMode, evaluators, handleJsonChange]);

  // ---------------------------------------------------------------------------
  // Cursor-position listener — auto-trigger suggestions for string values
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || !mounted) return;

    let timeout: number | null = null;
    const disposable = editor.onDidChangeCursorPosition(() => {
      if (timeout) window.clearTimeout(timeout);
      timeout = window.setTimeout(() => {
        const pos = editor.getPosition();
        const model = editor.getModel();
        if (!pos || !model) return;
        if (pos.lineNumber < 1 || pos.lineNumber > model.getLineCount()) return;

        const line = model.getLineContent(pos.lineNumber);
        const beforeCursor = line.substring(0, pos.column - 1);
        const afterCursor = line.substring(pos.column - 1);

        // Detect string value (not property key)
        const quotesBefore = beforeCursor.split('"').length - 1;
        const isInString =
          quotesBefore % 2 === 1 && /^[^"]*"/.test(afterCursor);
        const isPropertyKey =
          isInString && /^\s*:/.test(afterCursor.replace(/^[^"]*"/, ''));

        let shouldTrigger = false;

        if (isInString && !isPropertyKey) {
          const openIdx = beforeCursor.lastIndexOf('"');
          const closeIdx = afterCursor.indexOf('"');
          const len =
            openIdx >= 0 && closeIdx >= 0
              ? beforeCursor.length - openIdx - 1 + closeIdx
              : 999;

          if (len <= 2) {
            shouldTrigger = true;
          } else if (monacoRef.current) {
            // Only trigger for longer strings if we have domain suggestions
            shouldTrigger =
              getJsonEditorCompletionItems(
                monacoRef.current,
                model,
                pos,
                autocompleteContext
              ).length > 0;
          }
        }

        // Blank line inside object
        if (!shouldTrigger && /^\s*,?\s*$/.test(line)) {
          shouldTrigger = true;
        }

        if (shouldTrigger) {
          editor.trigger('cursor', 'editor.action.triggerSuggest', {});
        }
      }, 50);
    });

    return () => {
      if (timeout) window.clearTimeout(timeout);
      disposable.dispose();
    };
  }, [mounted, autocompleteContext]);

  // ---------------------------------------------------------------------------
  // Test harness (DOM helpers for Playwright)
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const root = editorRootRef.current;
    if (!root) return;

    root.__getJsonEditorValue = () => editorRef.current?.getValue() ?? '';
    root.__getJsonEditorLanguageId = () =>
      editorRef.current?.getModel()?.getLanguageId() ?? null;
    root.__isJsonEditorReady = () =>
      Boolean(editorRef.current && monacoRef.current);
    root.__focusJsonEditorAt = (lineNumber: number, column: number) => {
      if (!editorRef.current || !monacoRef.current) return;
      editorRef.current.setPosition(
        new monacoRef.current.Position(lineNumber, column)
      );
      editorRef.current.focus();
    };
    root.__setJsonEditorValue = (value: string) => {
      if (editorRef.current) {
        editorRef.current.setValue(value);
        editorRef.current.focus();
      }
      handleJsonChange(value);
    };
    root.__triggerJsonEditorSuggest = () => {
      const editor = editorRef.current;
      if (!editor) return;
      editor.focus();
      editor.trigger('keyboard', 'editor.action.triggerSuggest', {});
    };
    root.__getJsonEditorSuggestions = (lineNumber: number, column: number) => {
      if (!editorRef.current || !monacoRef.current) return [];
      const model = editorRef.current.getModel();
      if (!model) return [];
      return getJsonEditorCompletionItems(
        monacoRef.current,
        model,
        new monacoRef.current.Position(lineNumber, column),
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

  // ---------------------------------------------------------------------------
  // Validation
  // ---------------------------------------------------------------------------
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

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
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
            onChange={(value) => handleJsonChange(value ?? '')}
            onMount={handleEditorMount}
            options={{
              automaticLayout: true,
              quickSuggestions: {
                other: true,
                strings: true,
                comments: false,
              },
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
              guides: {
                bracketPairs: true,
                indentation: true,
              },
              stickyScroll: { enabled: true },
              padding: { top: 8, bottom: 8 },
              folding: true,
              showFoldingControls: 'mouseover',
              renderLineHighlight: 'line',
              cursorSmoothCaretAnimation: 'on',
              smoothScrolling: true,
            }}
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
