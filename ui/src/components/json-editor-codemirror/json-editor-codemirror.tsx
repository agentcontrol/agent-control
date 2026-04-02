import { json, jsonParseLinter } from '@codemirror/lang-json';
import { type Diagnostic, linter, lintGutter } from '@codemirror/lint';
import { type Extension } from '@codemirror/state';
import { EditorView, type ViewUpdate } from '@codemirror/view';
import { ActionIcon, Box, Group, Text, Tooltip } from '@mantine/core';
import { useClipboard } from '@mantine/hooks';
import {
  IconClipboardCheck,
  IconClipboardCopy,
  IconCode,
} from '@tabler/icons-react';
import createTheme from '@uiw/codemirror-themes';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { ProblemDetail, StepSchema } from '@/core/api/types';
import { LabelWithTooltip } from '@/core/components/label-with-tooltip';
import { ApiErrorAlert } from '@/core/page-components/agent-detail/modals/edit-control/api-error-alert';
import type {
  JsonEditorEvaluatorOption,
  JsonEditorMode,
  JsonSchema,
} from '@/core/page-components/agent-detail/modals/edit-control/types';

import {
  buildCodeMirrorJsonExtensions,
  buildCodeMirrorStandaloneDebugExtensions,
  computeAutoEdit,
  extractEvaluatorNames,
} from './json-editor-codemirror-language';

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

const theme = createTheme({
  theme: 'light',
  settings: {
    background: 'var(--mantine-color-body)',
    foreground: 'var(--mantine-color-text)',
    caret: 'var(--mantine-color-text)',
    gutterBackground: 'var(--mantine-color-body)',
    gutterBorder: 'var(--mantine-color-body)',
    gutterForeground: 'var(--mantine-color-dimmed)',
  },
  styles: [],
});

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
  const [isDarkMode] = useState(false);
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

  // useEffect(() => {
  //   const detect = () =>
  //     setIsDarkMode(
  //       document.documentElement.getAttribute('data-mantine-color-scheme') ===
  //         'dark'
  //     );
  //   detect();
  //   const obs = new MutationObserver(detect);
  //   obs.observe(document.documentElement, {
  //     attributes: true,
  //     attributeFilter: ['data-mantine-color-scheme'],
  //   });
  //   return () => obs.disconnect();
  // }, []);

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
    try {
      return (
        (JSON.parse(text) as { action?: { decision?: string } })?.action
          ?.decision ?? null
      );
    } catch {
      return null;
    }
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
        autoEditInProgressRef.current = false;
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
      view.dispatch({
        changes: {
          from: edit.offset,
          to: edit.offset + edit.length,
          insert: edit.newText,
        },
      });

      const nextText = view.state.doc.toString();
      previousEvaluatorNamesRef.current = extractEvaluatorNames(nextText);
      previousDecisionRef.current = parseDecision(nextText);
      internalChangeRef.current = true;
      handleJsonChange(nextText);
    },
    [
      editorMode,
      evaluators,
      handleJsonChange,
      parseDecision,
      effectiveDebugFlags.enableAutoEdits,
    ]
  );

  const extensions = useMemo<Extension[]>(
    () => [
      json(),
      ...(effectiveDebugFlags.enableLintExtensions
        ? [linter(jsonParseLinter()), lintGutter()]
        : []),
      DENSITY_THEME,
      ...domainExtensions,
      EditorView.updateListener.of(handleAutoEdits),
    ],
    [domainExtensions, effectiveDebugFlags.enableLintExtensions, handleAutoEdits]
  );

  const onEditorChange = useCallback(
    (value: string) => {
      internalChangeRef.current = true;
      handleJsonChange(value);
    },
    [handleJsonChange]
  );

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

  useEffect(() => {
    if (!validationError && lintErrors.length === 0) return;
  }, [lintErrors, validationError]);

  return (
    <Box>
      <Group justify="space-between" align="center" gap="xs">
        <LabelWithTooltip label={label} tooltip={tooltip} />
        <Group gap={4}>
          <Tooltip label="Format JSON" openDelay={400}>
            <ActionIcon
              variant="subtle"
              color="gray"
              size="sm"
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

      <Box ref={editorRootRef} mt={4} data-testid={testId}>
        {CodeMirrorComponent ? (
          <CodeMirrorComponent
            value={jsonText}
            onChange={onEditorChange}
            onUpdate={
              effectiveDebugFlags.enableLintExtensions ? handleLint : undefined
            }
            extensions={extensions}
            theme={isDarkMode ? 'dark' : theme}
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
        <Box mt="sm">
          <ApiErrorAlert error={validationError} unmappedErrors={[]} />
        </Box>
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
