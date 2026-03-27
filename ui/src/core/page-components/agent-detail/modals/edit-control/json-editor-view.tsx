import { ActionIcon, Box, Group, Text, Tooltip } from '@mantine/core';
import { useClipboard, useDebouncedValue } from '@mantine/hooks';
import { IconClipboardCheck, IconClipboardCopy, IconCode } from '@tabler/icons-react';
import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { isApiError } from '@/core/api/errors';
import { LabelWithTooltip } from '@/core/components/label-with-tooltip';

import { ApiErrorAlert } from './api-error-alert';
import {
  extractEvaluatorNames,
  findEvaluatorConfigEdit,
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
type MonacoEditorInstance = import('monaco-editor').editor.IStandaloneCodeEditor;

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

  // Read color scheme from the outer MantineProvider's DOM attribute
  // (useComputedColorScheme reads from the nearest provider which may be a nested one)
  useEffect(() => {
    const detectScheme = () => {
      const scheme =
        document.documentElement.getAttribute('data-mantine-color-scheme');
      setIsDarkMode(scheme === 'dark');
    };

    detectScheme();
    const observer = new MutationObserver(detectScheme);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-mantine-color-scheme'],
    });

    return () => observer.disconnect();
  }, []);

  const formatDocument = useCallback(() => {
    const editor = editorRef.current;
    if (!editor) return;

    // Fix missing commas first, then parse-and-reformat
    const text = editor.getValue();
    const commaFixed = fixJsonCommas(text);
    try {
      const formatted = JSON.stringify(JSON.parse(commaFixed), null, 2);
      if (formatted !== text) {
        editor.setValue(formatted);
        handleJsonChange(formatted);
      }
    } catch {
      // Comma fix helped but JSON still invalid — apply what we can
      if (commaFixed !== text) {
        editor.setValue(commaFixed);
        handleJsonChange(commaFixed);
      }
      editor.getAction('editor.action.formatDocument')?.run();
    }
  }, [handleJsonChange]);

  const copyToClipboard = useCallback(() => {
    const value = editorRef.current?.getValue() ?? jsonText;
    clipboard.copy(value);
  }, [clipboard, jsonText]);

  const handleEditorMount = useCallback(
    (editor: MonacoEditorInstance, monaco: MonacoModule) => {
      editorRef.current = editor;
      monacoRef.current = monaco;
      setMounted(true);
    },
    []
  );

  // Register completion provider and schema diagnostics.
  // Depends on `mounted` to re-run after Monaco finishes its async load.
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

  // Show inline value hints next to empty "" fields (e.g., "decision": ""  allow | deny | steer).
  // Hints disappear as soon as the user types a value.
  useEffect(() => {
    const editor = editorRef.current;
    const monaco = monacoRef.current;
    if (!editor || !monaco || !mounted) return;

    const hintClassName = 'json-editor-value-hint';
    const styleElement = document.createElement('style');
    styleElement.textContent = `.${hintClassName} { color: var(--mantine-color-gray-5); font-style: italic; }`;
    document.head.appendChild(styleElement);

    const decorationCollection = editor.createDecorationsCollection();

    const updateHints = () => {
      const model = editor.getModel();
      if (!model) return;

      try {
        const hints = getEmptyValueHints(monaco, model, autocompleteContext);
        decorationCollection.set(
          hints.map((hint) => ({
            range: hint.range,
            options: {
              after: {
                content: hint.hint,
                inlineClassName: hintClassName,
                cursorStops:
                  monaco.editor.InjectedTextCursorStops.None,
              },
            },
          }))
        );
      } catch {
        decorationCollection.clear();
      }
    };

    updateHints();
    const disposable = editor.onDidChangeModelContent(() => {
      updateHints();
    });

    return () => {
      disposable.dispose();
      decorationCollection.clear();
      styleElement.remove();
    };
  }, [mounted, autocompleteContext]);

  // Auto-trigger suggestions when cursor enters a string VALUE or array item.
  // Only triggers for strings (not property keys, not inside {}/[]).
  // Users type " to get property suggestions in objects — this avoids
  // the suggest widget intercepting Enter when the user wants a newline.
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

        // Only trigger for string VALUES and array items, never property keys.
        // A property key has ":" right after its closing quote; values don't.
        const quotesBefore = beforeCursor.split('"').length - 1;
        const hasClosingQuote = /^[^"]*"/.test(afterCursor);
        const isInString = quotesBefore % 2 === 1 && hasClosingQuote;
        const isPropertyKey =
          isInString && /^\s*:/.test(afterCursor.replace(/^[^"]*"/, ''));

        // Also trigger on blank/whitespace lines inside objects (safe because
        // acceptSuggestionOnEnter is 'off' — Enter always creates a newline).
        const isBlankOrCommaLine = /^\s*,?\s*$/.test(line);

        if ((isInString && !isPropertyKey) || isBlankOrCommaLine) {
          editor.trigger('cursor', 'editor.action.triggerSuggest', {});
        }
      }, 50);
    });

    return () => {
      if (timeout) window.clearTimeout(timeout);
      disposable.dispose();
    };
  }, [mounted]);

  // Auto-fix missing commas after a pause in typing.
  // Uses jsonc-parser to detect CommaExpected errors and insert commas.
  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || !mounted) return;

    let timeout: number | null = null;
    const disposable = editor.onDidChangeModelContent(() => {
      if (timeout) window.clearTimeout(timeout);
      timeout = window.setTimeout(() => {
        const text = editor.getValue();
        const fixed = fixJsonCommas(text);
        if (fixed !== text) {
          const pos = editor.getPosition();
          editor.setValue(fixed);
          if (pos) editor.setPosition(pos);
          handleJsonChange(fixed);
        }
      }, 800);
    });

    return () => {
      if (timeout) window.clearTimeout(timeout);
      disposable.dispose();
    };
  }, [mounted, handleJsonChange]);

  // When an evaluator name changes in control mode, auto-update the config
  // to match the new evaluator's schema (e.g., regex→list resets config).
  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || !mounted || editorMode !== 'control') return;

    let previousNames = extractEvaluatorNames(editor.getValue());

    const disposable = editor.onDidChangeModelContent(() => {
      const text = editor.getValue();
      const edit = findEvaluatorConfigEdit(text, previousNames, evaluators);
      previousNames = extractEvaluatorNames(text);

      if (!edit) return;

      const model = editor.getModel();
      if (!model) return;

      const startPos = model.getPositionAt(edit.offset);
      const endPos = model.getPositionAt(edit.offset + edit.length);

      // Defer edit to avoid modifying the model inside its own change event.
      // After inserting, reformat the entire document so indentation stays clean.
      queueMicrotask(() => {
        editor.executeEdits('evaluator-config-update', [
          {
            range: {
              startLineNumber: startPos.lineNumber,
              startColumn: startPos.column,
              endLineNumber: endPos.lineNumber,
              endColumn: endPos.column,
            },
            text: edit.newText,
          },
        ]);
        try {
          const formatted = JSON.stringify(
            JSON.parse(editor.getValue()),
            null,
            2
          );
          editor.setValue(formatted);
          handleJsonChange(formatted);
        } catch {
          handleJsonChange(editor.getValue());
        }
      });
    });

    return () => disposable.dispose();
  }, [mounted, editorMode, evaluators, handleJsonChange]);

  useEffect(() => {
    const root = editorRootRef.current;
    if (!root) return;

    root.__getJsonEditorValue = () => editorRef.current?.getValue() ?? jsonText;
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
  }, [autocompleteContext, handleJsonChange, jsonText]);

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
            jsonError ? 'var(--mantine-color-red-6)' : 'var(--mantine-color-gray-4)'
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
