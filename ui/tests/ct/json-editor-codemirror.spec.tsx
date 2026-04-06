/// <reference path="./playwright-jsx-runtime.d.ts" />
/** @jsxImportSource playwright */

/**
 * Playwright component tests: real browser, Vite bundle, no Next.js server.
 *
 * The pragma uses `playwright/jsx-runtime` (see `playwright` package exports). Root
 * `tsconfig.json` uses `"jsx": "preserve"` for Next.js; without this, `mount()` would
 * serialize raw function components and the CT bundle rejects them.
 */

import { expect, test } from '@playwright/experimental-ct-react';

// One binding per import: CT Babel only strips/replaces imports whose specifiers are
// all JSX tag names; mixing `CT_JSON_EDITOR_TEST_ID` with the host leaves a real
// function reference and mount() fails to serialize the component.
import { JsonEditorCodeMirrorCtHost } from '../../src/components/json-editor-codemirror/json-editor-codemirror.playwright-story';
import { CT_JSON_EDITOR_TEST_ID } from '../../src/components/json-editor-codemirror/json-editor-codemirror.playwright-story';
import {
  focusJsonEditorAt,
  getJsonEditorSuggestions,
  getJsonEditorValue,
  setJsonEditorValue,
} from '../json-editor-bridge';

const EDITOR = CT_JSON_EDITOR_TEST_ID;

test.describe('JsonEditorCodeMirror (component)', () => {
  test('evaluator-config mode loads empty object document', async ({
    mount,
    page,
  }) => {
    await mount(<JsonEditorCodeMirrorCtHost mode="evaluator-config" />);
    await expect(
      page.getByTestId('json-editor-codemirror-ct-host')
    ).toBeVisible();
    const raw = await getJsonEditorValue(page, EDITOR);
    expect(JSON.parse(raw)).toEqual({});
  });

  test('control mode loads minimal valid control document', async ({
    mount,
    page,
  }) => {
    await mount(<JsonEditorCodeMirrorCtHost mode="control" />);
    const raw = await getJsonEditorValue(page, EDITOR);
    const parsed = JSON.parse(raw) as {
      execution: string;
      condition: unknown;
      action: { decision: string };
    };
    expect(parsed.execution).toBe('server');
    expect(parsed.condition).toEqual({});
    expect(parsed.action).toEqual({ decision: 'allow' });
  });

  test('setJsonEditorValue updates document', async ({ mount, page }) => {
    await mount(<JsonEditorCodeMirrorCtHost mode="evaluator-config" />);
    const next = JSON.stringify({ threshold: 0.5, enabled: true });
    await setJsonEditorValue(page, EDITOR, next);
    expect(JSON.parse(await getJsonEditorValue(page, EDITOR))).toEqual({
      threshold: 0.5,
      enabled: true,
    });
  });

  test('keyboard typing inserts text at cursor', async ({ mount, page }) => {
    await mount(<JsonEditorCodeMirrorCtHost mode="evaluator-config" />);
    expect(JSON.parse(await getJsonEditorValue(page, EDITOR))).toEqual({});

    await focusJsonEditorAt(page, EDITOR, 1, 2);
    await page.keyboard.type('"typedKey": 42', { delay: 15 });

    expect(JSON.parse(await getJsonEditorValue(page, EDITOR))).toEqual({
      typedKey: 42,
    });
  });

  test('replace sample sets minified control JSON', async ({ mount, page }) => {
    await mount(<JsonEditorCodeMirrorCtHost mode="control" />);
    await page.getByTestId('ct-replace-sample').click();
    expect(JSON.parse(await getJsonEditorValue(page, EDITOR))).toEqual({
      execution: 'sdk',
      condition: { selector: { path: '*' } },
      action: { decision: 'deny' },
    });
  });

  test('format pretty-prints without changing parsed data', async ({
    mount,
    page,
  }) => {
    await mount(<JsonEditorCodeMirrorCtHost mode="control" />);
    await page.getByTestId('ct-replace-sample').click();
    const before = await getJsonEditorValue(page, EDITOR);
    expect(before.includes('\n')).toBe(false);

    await page.getByRole('button', { name: 'Format document' }).click();

    const after = await getJsonEditorValue(page, EDITOR);
    expect(after.includes('\n')).toBe(true);
    expect(JSON.parse(after)).toEqual(JSON.parse(before));
  });

  test('format preserves commas that are part of string values', async ({
    mount,
    page,
  }) => {
    await mount(<JsonEditorCodeMirrorCtHost mode="control" />);
    const before = JSON.stringify(
      {
        execution: 'server',
        condition: {
          selector: { path: 'output' },
          evaluator: {
            name: 'regex',
            config: { pattern: 'a,}' },
          },
        },
        action: { decision: 'deny' },
      },
      null,
      2
    );

    await setJsonEditorValue(page, EDITOR, before);
    await page.getByRole('button', { name: 'Format document' }).click();

    const after = JSON.parse(await getJsonEditorValue(page, EDITOR)) as {
      condition: { evaluator: { config: { pattern: string } } };
    };
    expect(after.condition.evaluator.config.pattern).toBe('a,}');
  });

  test('toggle jsonError shows parent message', async ({ mount, page }) => {
    await mount(<JsonEditorCodeMirrorCtHost mode="evaluator-config" />);
    await page.getByTestId('ct-toggle-json-error').click();
    await expect(
      page.getByText('Simulated invalid JSON message from parent')
    ).toBeVisible();
    await page.getByTestId('ct-toggle-json-error').click();
    await expect(
      page.getByText('Simulated invalid JSON message from parent')
    ).toHaveCount(0);
  });

  test('helperText is visible', async ({ mount, page }) => {
    await mount(<JsonEditorCodeMirrorCtHost mode="evaluator-config" />);
    await expect(
      page.getByText('Playwright CT mounts this host without a Next.js page.')
    ).toBeVisible();
  });

  test('control mode suggests root schema properties', async ({
    mount,
    page,
  }) => {
    await mount(<JsonEditorCodeMirrorCtHost mode="control" />);
    await setJsonEditorValue(page, EDITOR, '{}');
    const items = await getJsonEditorSuggestions(page, EDITOR, 1, 2);
    const labels = items.map((i) => i.label);
    expect(labels).toContain('condition');
    expect(labels).toContain('action');
    expect(labels).toContain('execution');
  });

  test('remounting host switches mode document', async ({ mount, page }) => {
    let host = await mount(
      <JsonEditorCodeMirrorCtHost mode="evaluator-config" />
    );
    expect(JSON.parse(await getJsonEditorValue(page, EDITOR))).toEqual({});

    await host.unmount();
    host = await mount(<JsonEditorCodeMirrorCtHost mode="control" />);
    const controlParse = JSON.parse(await getJsonEditorValue(page, EDITOR)) as {
      execution?: string;
    };
    expect(controlParse.execution).toBe('server');

    await host.unmount();
    await mount(<JsonEditorCodeMirrorCtHost mode="evaluator-config" />);
    expect(JSON.parse(await getJsonEditorValue(page, EDITOR))).toEqual({});
  });

  test('invalid JSON stays readable; format does not silently fix', async ({
    mount,
    page,
  }) => {
    await mount(<JsonEditorCodeMirrorCtHost mode="evaluator-config" />);
    const broken = '{"a":1';
    await setJsonEditorValue(page, EDITOR, broken);
    expect(await getJsonEditorValue(page, EDITOR)).toBe(broken);

    await page.getByRole('button', { name: 'Format document' }).click();
    const after = await getJsonEditorValue(page, EDITOR);
    expect(() => JSON.parse(after)).toThrow();
  });
});
