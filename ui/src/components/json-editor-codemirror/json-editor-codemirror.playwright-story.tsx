import { Box, Button, Group } from '@mantine/core';
import { useCallback, useEffect, useState } from 'react';

import type {
  JsonEditorEvaluatorOption,
  JsonEditorMode,
} from '@/core/page-components/agent-detail/modals/edit-control/types';

import { HARNESS_CONTROL_SCHEMA } from './harness-schema';
import { JsonEditorCodeMirror } from './json-editor-codemirror';

/** `data-testid` on the editor root for `tests/json-editor-bridge.ts` helpers. */
export const CT_JSON_EDITOR_TEST_ID = 'codemirror-json-editor-ct';

const DEFAULT_CONTROL_JSON =
  '{"execution":"server","condition":{},"action":{"decision":"allow"}}';

const CT_EVALUATORS: JsonEditorEvaluatorOption[] = [
  {
    id: 'regex',
    label: 'Regex',
    source: 'global',
    configSchema: {
      type: 'object',
      properties: {
        pattern: { type: 'string', default: '.*' },
      },
      required: ['pattern'],
    },
  },
  {
    id: 'json',
    label: 'JSON',
    source: 'global',
    configSchema: {
      type: 'object',
      properties: {
        json_schema: { type: 'object', additionalProperties: true },
      },
    },
  },
];

/** Host for Playwright component tests only (see `tests/ct/json-editor-codemirror.spec.tsx`). */
export function JsonEditorCodeMirrorCtHost({ mode }: { mode: JsonEditorMode }) {
  const [jsonText, setJsonText] = useState(() =>
    mode === 'control' ? DEFAULT_CONTROL_JSON : '{}'
  );
  const [jsonError, setJsonError] = useState<string | null>(null);

  useEffect(() => {
    queueMicrotask(() => {
      setJsonText(mode === 'control' ? DEFAULT_CONTROL_JSON : '{}');
      setJsonError(null);
    });
  }, [mode]);

  const handleJsonChange = useCallback((next: string) => {
    setJsonText(next);
  }, []);

  return (
    <Box data-testid="json-editor-codemirror-ct-host">
      <Group mb="sm">
        <Button
          type="button"
          variant="subtle"
          data-testid="ct-toggle-json-error"
          onClick={() =>
            setJsonError((prev) =>
              prev ? null : 'Simulated invalid JSON message from parent'
            )
          }
        >
          Toggle json error
        </Button>
        {mode === 'control' ? (
          <Button
            type="button"
            variant="subtle"
            data-testid="ct-replace-sample"
            onClick={() =>
              setJsonText(
                '{"execution":"sdk","condition":{"selector":{"path":"*"}},"action":{"decision":"deny"}}'
              )
            }
          >
            Replace sample (minified)
          </Button>
        ) : null}
      </Group>
      <JsonEditorCodeMirror
        jsonText={jsonText}
        handleJsonChange={handleJsonChange}
        jsonError={jsonError}
        setJsonError={setJsonError}
        editorMode={mode}
        schema={mode === 'control' ? HARNESS_CONTROL_SCHEMA : null}
        evaluators={mode === 'control' ? CT_EVALUATORS : undefined}
        testId={CT_JSON_EDITOR_TEST_ID}
        label="JSON editor (component test)"
        helperText="Playwright CT mounts this host without a Next.js page."
      />
    </Box>
  );
}
