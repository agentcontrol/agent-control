import { closeCompletion, startCompletion } from '@codemirror/autocomplete';
import { json, jsonParseLinter } from '@codemirror/lang-json';
import { type Diagnostic, linter, lintGutter } from '@codemirror/lint';
import { EditorSelection, type Extension } from '@codemirror/state';
import { EditorView, type ViewUpdate } from '@codemirror/view';
import {
  ActionIcon,
  Box,
  Group,
  NativeSelect,
  Text,
  Tooltip,
  useMantineColorScheme,
} from '@mantine/core';
import { useClipboard, useDebouncedValue } from '@mantine/hooks';
import {
  IconClipboardCheck,
  IconClipboardCopy,
  IconCode,
} from '@tabler/icons-react';
import { findNodeAtLocation, parseTree } from 'jsonc-parser';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { isApiError } from '@/core/api/errors';
import type { ProblemDetail, StepSchema } from '@/core/api/types';
import { LabelWithTooltip } from '@/core/components/label-with-tooltip';
import { ApiErrorAlert } from '@/core/page-components/agent-detail/modals/edit-control/api-error-alert';
import type {
  JsonEditorEvaluatorOption,
  JsonEditorMode,
  JsonSchema,
} from '@/core/page-components/agent-detail/modals/edit-control/types';

import {
  CODE_MIRROR_DARK_THEME_PRESETS,
  CODE_MIRROR_LIGHT_THEME_PRESETS,
  DEFAULT_DARK_THEME_ID,
  DEFAULT_LIGHT_THEME_ID,
  mantineLightCodeMirrorTheme,
  readStoredCodeMirrorThemePrefs,
  type StoredCodeMirrorThemePrefs,
  writeStoredCodeMirrorThemePrefs,
} from './codemirror-theme-presets';
import {
  buildCodeMirrorInlineServerValidationErrorsExtension,
  buildCodeMirrorJsonExtensions,
  buildCodeMirrorStandaloneDebugExtensions,
  canRenderInlineServerValidationError,
  caretAfterPrettyJsonReplace,
  computeAutoEdit,
  extractEvaluatorNames,
  fixJsonCommas,
  getCodeMirrorCompletionItems,
  setInlineServerValidationErrorsEffect,
  tryFormat,
} from './json-editor-codemirror-language';
import type { JsonEditorCodeMirrorContext } from './language/types';

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
const DEFAULT_LABEL = 'Configuration (JSON)';
const DEFAULT_TOOLTIP = 'Raw JSON configuration';
const DEFAULT_TEST_ID = 'raw-json-textarea';
const DEFAULT_VALIDATE_DEBOUNCE_MS = 500;

const DENSITY_THEME = EditorView.theme({
  '&': {
    fontSize: '12px',
    fontFamily:
      'ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, monospace',
  },
  '.cm-scroller': {
    fontFamily:
      'ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, monospace',
    lineHeight: '1.4',
  },
});

/** Default @codemirror/autocomplete uses maxHeight ~10em; long lists clip the last items. */
const AUTOCOMPLETE_LIST_THEME = EditorView.theme({
  '.cm-tooltip.cm-tooltip-autocomplete > ul': {
    maxHeight: 'min(24em, 55vh)',
    scrollbarGutter: 'stable',
  },
});

type CodeMirrorComponentType = typeof import('@uiw/react-codemirror').default;

export type JsonEditorCodeMirrorProps = {
  jsonText: string;
  handleJsonChange: (text: string) => void;
  jsonError?: string | null;
  setJsonError?: (error: string | null) => void;
  validationError?: ProblemDetail | null;
  setValidationError?: (error: ProblemDetail | null) => void;
  onValidateConfig?: (
    config: Record<string, unknown>,
    options?: { signal?: AbortSignal }
  ) => Promise<void>;
  onValidationStatusChange?: (
    status: 'idle' | 'validating' | 'valid' | 'invalid'
  ) => void;
  validateDebounceMs?: number;
  height?: number;
  label?: string;
  tooltip?: string;
  helperText?: React.ReactNode;
  testId?: string;
  editorMode?: JsonEditorMode;
  schema?: JsonSchema | null;
  evaluators?: JsonEditorEvaluatorOption[];
  activeEvaluatorId?: string | null;
  steps?: StepSchema[];
  debugFlags?: {
    enableBasicSetupExtension?: boolean;
    enableAutoEdits?: boolean;
    enableExternalSync?: boolean;
    enableLintExtensions?: boolean;
    useStandaloneCompletionSource?: boolean;
  };
};

export function JsonEditorCodeMirror({
  jsonText,
  handleJsonChange,
  jsonError,
  validationError,
  onValidateConfig,
  onValidationStatusChange,
  setJsonError,
  setValidationError,
  validateDebounceMs,
  height = DEFAULT_HEIGHT,
  label = DEFAULT_LABEL,
  tooltip = DEFAULT_TOOLTIP,
  helperText,
  testId = DEFAULT_TEST_ID,
  editorMode = 'evaluator-config',
  schema,
  evaluators,
  activeEvaluatorId,
  steps,
  debugFlags,
}: JsonEditorCodeMirrorProps) {
  const [CodeMirrorComponent, setCodeMirrorComponent] =
    useState<CodeMirrorComponentType | null>(null);
  const { colorScheme } = useMantineColorScheme();
  const isDarkMode = colorScheme === 'dark';
  const [cmThemePrefs, setCmThemePrefs] = useState<StoredCodeMirrorThemePrefs>(
    () => readStoredCodeMirrorThemePrefs()
  );
  const [isReady, setIsReady] = useState(false);
  const [lintErrors, setLintErrors] = useState<string[]>([]);
  const editorViewRef = useRef<EditorView | null>(null);
  const editorRootRef = useRef<JsonEditorTestElement | null>(null);
  const internalChangeRef = useRef(false);
  const autoEditInProgressRef = useRef(false);
  const previousEvaluatorNamesRef = useRef<Map<string, string>>(new Map());
  const previousDecisionRef = useRef<string | null>(null);
  const clipboard = useClipboard({ timeout: 1500 });

  const effectiveDebugFlags = {
    enableBasicSetupExtension: true,
    enableAutoEdits: true,
    enableExternalSync: true,
    enableLintExtensions: true,
    useStandaloneCompletionSource: false,
    ...debugFlags,
  };

  useEffect(() => {
    const loadModules = async () => {
      const codeMirrorModule = await import('@uiw/react-codemirror');
      setCodeMirrorComponent(() => codeMirrorModule.default);
    };
    void loadModules();
  }, []);

  useEffect(() => {
    setCmThemePrefs((prev) => {
      const darkOk =
        Object.prototype.hasOwnProperty.call(
          CODE_MIRROR_DARK_THEME_PRESETS,
          prev.dark
        ) ||
        Object.prototype.hasOwnProperty.call(
          CODE_MIRROR_LIGHT_THEME_PRESETS,
          prev.dark
        );
      const lightOk =
        Object.prototype.hasOwnProperty.call(
          CODE_MIRROR_LIGHT_THEME_PRESETS,
          prev.light
        ) ||
        Object.prototype.hasOwnProperty.call(
          CODE_MIRROR_DARK_THEME_PRESETS,
          prev.light
        );
      if (darkOk && lightOk) return prev;
      const next: StoredCodeMirrorThemePrefs = {
        dark: darkOk ? prev.dark : DEFAULT_DARK_THEME_ID,
        light: lightOk ? prev.light : DEFAULT_LIGHT_THEME_ID,
      };
      writeStoredCodeMirrorThemePrefs(next);
      return next;
    });
  }, []);

  const domainExtensions = useMemo<Extension[]>(() => {
    if (effectiveDebugFlags.useStandaloneCompletionSource) {
      return buildCodeMirrorStandaloneDebugExtensions();
    }
    return buildCodeMirrorJsonExtensions({
      mode: editorMode,
      schema,
      evaluators,
      activeEvaluatorId,
      steps,
    });
  }, [
    activeEvaluatorId,
    editorMode,
    effectiveDebugFlags.useStandaloneCompletionSource,
    evaluators,
    schema,
    steps,
  ]);

  const parseDecision = useCallback((text: string): string | null => {
    const tree = parseTree(text);
    if (!tree) return null;
    const node = findNodeAtLocation(tree, ['action', 'decision']);
    return typeof node?.value === 'string' ? node.value : null;
  }, []);

  useEffect(() => {
    previousEvaluatorNamesRef.current = extractEvaluatorNames(jsonText);
    previousDecisionRef.current = parseDecision(jsonText);
  }, [jsonText, parseDecision]);

  const handleAutoEdits = useCallback(
    (update: ViewUpdate) => {
      if (!effectiveDebugFlags.enableAutoEdits) return;
      if (!update.docChanged) return;
      if (autoEditInProgressRef.current) {
        return;
      }

      const view = update.view;
      const text = view.state.doc.toString();
      const { edit, nextEvaluatorNames, nextDecision } = computeAutoEdit(
        text,
        previousEvaluatorNamesRef.current,
        previousDecisionRef.current,
        editorMode,
        evaluators
      );

      previousEvaluatorNamesRef.current = nextEvaluatorNames;
      previousDecisionRef.current = nextDecision;

      if (!edit) return;

      autoEditInProgressRef.current = true;
      try {
        view.dispatch({
          changes: {
            from: edit.offset,
            to: edit.offset + edit.length,
            insert: edit.newText,
          },
        });
        closeCompletion(view);

        let nextText = view.state.doc.toString();
        // `JSON.stringify(..., 2)` for new config starts at column 0; re-format the
        // whole document so nesting matches the editor (same as the Prettify action).
        const commaFixed = fixJsonCommas(nextText);
        const formatted = tryFormat(commaFixed);
        const pretty =
          formatted && formatted !== nextText ? formatted : commaFixed;
        if (pretty !== nextText) {
          const caretBeforeFormat = view.state.selection.main.head;
          const mappedCaret = caretAfterPrettyJsonReplace(
            nextText,
            caretBeforeFormat,
            pretty
          );
          view.dispatch({
            changes: { from: 0, to: nextText.length, insert: pretty },
            selection:
              mappedCaret != null
                ? EditorSelection.single(mappedCaret)
                : undefined,
            scrollIntoView: true,
          });
          nextText = view.state.doc.toString();
        }

        previousEvaluatorNamesRef.current = extractEvaluatorNames(nextText);
        previousDecisionRef.current = parseDecision(nextText);
        internalChangeRef.current = true;
        handleJsonChange(nextText);
      } finally {
        autoEditInProgressRef.current = false;
      }
    },
    [
      editorMode,
      evaluators,
      handleJsonChange,
      parseDecision,
      effectiveDebugFlags.enableAutoEdits,
    ]
  );

  const inlineServerValidationExtension = useMemo(
    () => buildCodeMirrorInlineServerValidationErrorsExtension(),
    []
  );

  const extensions = useMemo<Extension[]>(
    () => [
      json(),
      ...(effectiveDebugFlags.enableLintExtensions
        ? [linter(jsonParseLinter()), lintGutter()]
        : []),
      DENSITY_THEME,
      ...domainExtensions,
      AUTOCOMPLETE_LIST_THEME,
      EditorView.updateListener.of(handleAutoEdits),
      inlineServerValidationExtension,
    ],
    [
      domainExtensions,
      effectiveDebugFlags.enableLintExtensions,
      handleAutoEdits,
      inlineServerValidationExtension,
    ]
  );

  const completionContext = useMemo<JsonEditorCodeMirrorContext>(
    () => ({
      mode: editorMode,
      schema,
      evaluators,
      activeEvaluatorId,
      steps,
    }),
    [activeEvaluatorId, editorMode, evaluators, schema, steps]
  );

  useEffect(() => {
    const root = editorRootRef.current;
    if (!root) return;

    const lineColumnToPosition = (
      lineNumber: number,
      column: number
    ): number => {
      const view = editorViewRef.current;
      if (!view) return 0;
      const doc = view.state.doc;
      const ln = Math.min(Math.max(lineNumber, 1), doc.lines);
      const line = doc.line(ln);
      const col = Math.max(1, column);
      return Math.min(line.from + (col - 1), line.to);
    };

    root.__getJsonEditorValue = () =>
      editorViewRef.current?.state.doc.toString() ?? '';
    root.__getJsonEditorLanguageId = () => 'json';
    root.__isJsonEditorReady = () =>
      Boolean(CodeMirrorComponent && isReady && editorViewRef.current);
    root.__focusJsonEditorAt = (lineNumber, column) => {
      const view = editorViewRef.current;
      if (!view) return;
      const pos = lineColumnToPosition(lineNumber, column);
      view.dispatch({
        selection: EditorSelection.single(pos),
        scrollIntoView: true,
      });
      view.focus();
    };
    root.__setJsonEditorValue = (nextValue) => {
      const view = editorViewRef.current;
      if (!view) return;
      internalChangeRef.current = true;
      const len = view.state.doc.length;
      view.dispatch({
        changes: { from: 0, to: len, insert: nextValue },
      });
      handleJsonChange(nextValue);
      view.focus();
    };
    root.__triggerJsonEditorSuggest = () => {
      const view = editorViewRef.current;
      if (!view) return;
      view.focus();
      void startCompletion(view);
    };
    root.__getJsonEditorSuggestions = (lineNumber, column) => {
      const view = editorViewRef.current;
      if (!view) return [];
      const pos = lineColumnToPosition(lineNumber, column);
      const text = view.state.doc.toString();
      return getCodeMirrorCompletionItems(text, pos, completionContext);
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
  }, [CodeMirrorComponent, completionContext, handleJsonChange, isReady]);

  const [debouncedJsonText] = useDebouncedValue(
    jsonText,
    validateDebounceMs ?? DEFAULT_VALIDATE_DEBOUNCE_MS
  );

  const validationAbortControllerRef = useRef<AbortController | null>(null);

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

    validationAbortControllerRef.current?.abort();
    const controller = new AbortController();
    validationAbortControllerRef.current = controller;

    setJsonError?.(null);
    onValidationStatusChange?.('validating');

    onValidateConfig(parsed, { signal: controller.signal })
      .then(() => {
        if (controller.signal.aborted) return;
        setValidationError?.(null);
        onValidationStatusChange?.('valid');
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (isApiError(error)) {
          setValidationError?.(error.problemDetail);
          onValidationStatusChange?.('invalid');
          return;
        }
        setJsonError?.('Validation failed.');
        setValidationError?.(null);
        onValidationStatusChange?.('invalid');
      });

    return () => controller.abort();
  }, [
    onValidateConfig,
    debouncedJsonText,
    onValidationStatusChange,
    setJsonError,
    setValidationError,
  ]);

  const onEditorChange = useCallback(
    (value: string) => {
      internalChangeRef.current = true;
      handleJsonChange(value);
    },
    [handleJsonChange]
  );

  const formatJson = useCallback(() => {
    const view = editorViewRef.current;
    if (!view) return;

    const current = view.state.doc.toString();
    const commaFixed = fixJsonCommas(current);
    const formatted = tryFormat(commaFixed);

    const next = formatted && formatted !== current ? formatted : commaFixed;
    if (next === current) return;

    internalChangeRef.current = true;
    view.dispatch({
      changes: { from: 0, to: current.length, insert: next },
    });
  }, []);

  // Keep this block to test parent->editor sync behavior.
  useEffect(() => {
    if (!effectiveDebugFlags.enableExternalSync) return;
    const view = editorViewRef.current;
    if (!view) return;
    if (internalChangeRef.current) {
      internalChangeRef.current = false;
      return;
    }
    const currentDoc = view.state.doc.toString();
    if (currentDoc !== jsonText) {
      view.dispatch({
        changes: { from: 0, to: currentDoc.length, insert: jsonText },
      });
    }
  }, [effectiveDebugFlags.enableExternalSync, jsonText]);

  const handleLint = useCallback(({ view }: ViewUpdate) => {
    const diagnostics: Diagnostic[] = jsonParseLinter()(view);
    setLintErrors(diagnostics.map((d) => d.message));
  }, []);

  // Push latest server validation errors into a CodeMirror state field,
  // avoiding a full editor reconfigure on each validation response.
  useEffect(() => {
    const view = editorViewRef.current;
    if (!view) return;

    const errors = validationError?.errors ?? [];
    view.dispatch({
      effects: setInlineServerValidationErrorsEffect.of({ errors }),
    });
  }, [validationError]);

  useEffect(() => {
    if (!validationError && lintErrors.length === 0) return;
  }, [lintErrors, validationError]);

  const unmappedValidationErrors = useMemo(() => {
    const errors = validationError?.errors ?? [];
    return errors
      .filter((error) => !canRenderInlineServerValidationError(jsonText, error))
      .map((e) => ({ field: e.field, message: e.message }));
  }, [jsonText, validationError]);

  const codeMirrorTheme = useMemo(() => {
    const selectedId = isDarkMode ? cmThemePrefs.dark : cmThemePrefs.light;
    const selectedExtension =
      CODE_MIRROR_DARK_THEME_PRESETS[selectedId]?.extension ??
      CODE_MIRROR_LIGHT_THEME_PRESETS[selectedId]?.extension ??
      (isDarkMode
        ? CODE_MIRROR_DARK_THEME_PRESETS[DEFAULT_DARK_THEME_ID].extension
        : mantineLightCodeMirrorTheme);
    return selectedExtension;
  }, [isDarkMode, cmThemePrefs.dark, cmThemePrefs.light]);

  const cmThemeSelectData = useMemo(
    () =>
      [
        ...Object.entries(CODE_MIRROR_DARK_THEME_PRESETS),
        ...Object.entries(CODE_MIRROR_LIGHT_THEME_PRESETS),
      ].map(([value, { label: optionLabel }]) => ({
        value,
        label: optionLabel,
      })),
    []
  );

  const cmThemeSelectValue = useMemo(() => {
    const raw = isDarkMode ? cmThemePrefs.dark : cmThemePrefs.light;
    const inDark = Object.prototype.hasOwnProperty.call(
      CODE_MIRROR_DARK_THEME_PRESETS,
      raw
    );
    const inLight = Object.prototype.hasOwnProperty.call(
      CODE_MIRROR_LIGHT_THEME_PRESETS,
      raw
    );
    if (inDark || inLight) return raw;
    return isDarkMode ? DEFAULT_DARK_THEME_ID : DEFAULT_LIGHT_THEME_ID;
  }, [isDarkMode, cmThemePrefs.dark, cmThemePrefs.light]);

  return (
    <Box>
      <Group justify="space-between" align="center" gap="xs" wrap="nowrap">
        <LabelWithTooltip label={label} tooltip={tooltip} />
        <Group gap="xs" wrap="nowrap" justify="flex-end" style={{ flex: 1 }}>
          <NativeSelect
            size="xs"
            title="Editor color theme"
            aria-label="CodeMirror editor color theme"
            style={{ flex: '0 1 220px', maxWidth: 260 }}
            data={cmThemeSelectData}
            value={cmThemeSelectValue}
            onChange={(event) => {
              const value = event.currentTarget.value;
              setCmThemePrefs((prev) => {
                const next: StoredCodeMirrorThemePrefs = isDarkMode
                  ? { ...prev, dark: value }
                  : { ...prev, light: value };
                writeStoredCodeMirrorThemePrefs(next);
                return next;
              });
            }}
          />
          <Group gap={4}>
            <Tooltip label="Format JSON" openDelay={400}>
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                aria-label="Format document"
                onClick={formatJson}
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
                onClick={() => clipboard.copy(jsonText)}
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
      </Group>

      <Box ref={editorRootRef} mt={4} data-testid={testId}>
        {CodeMirrorComponent ? (
          <CodeMirrorComponent
            value={jsonText}
            onChange={onEditorChange}
            onUpdate={
              effectiveDebugFlags.enableLintExtensions ? handleLint : undefined
            }
            extensions={extensions}
            theme={codeMirrorTheme}
            basicSetup={
              effectiveDebugFlags.enableBasicSetupExtension
                ? {
                    lineNumbers: true,
                    foldGutter: true,
                    highlightActiveLine: true,
                  }
                : false
            }
            height={`${height}px`}
            onCreateEditor={(view) => {
              editorViewRef.current = view;
              setIsReady(true);
            }}
          />
        ) : (
          <Box p="sm">
            <Text size="xs" c="dimmed">
              Loading CodeMirror...
            </Text>
          </Box>
        )}
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
        unmappedValidationErrors.length > 0 ? (
          <Box mt="sm">
            <ApiErrorAlert
              error={validationError}
              unmappedErrors={unmappedValidationErrors}
            />
          </Box>
        ) : null
      ) : null}
      <Box
        data-testid={`${testId}-codemirror-ready`}
        style={{ display: 'none' }}
        aria-hidden
      >
        {isReady ? 'ready' : 'not-ready'}
      </Box>
    </Box>
  );
}
