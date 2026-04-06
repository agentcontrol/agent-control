import { expect, type Page } from '@playwright/test';

export async function getJsonEditorValue(
  page: Page,
  testId: string
): Promise<string> {
  const locator = page.getByTestId(testId);
  await expect(locator).toBeVisible();
  await page.waitForFunction((selector) => {
    const element = document.querySelector(`[data-testid="${selector}"]`) as {
      __getJsonEditorValue?: () => string;
      __isJsonEditorReady?: () => boolean;
    } | null;

    return (
      typeof element?.__getJsonEditorValue === 'function' &&
      element.__isJsonEditorReady?.() === true
    );
  }, testId);

  return locator.evaluate((element) => {
    const target = element as { __getJsonEditorValue?: () => string };
    return target.__getJsonEditorValue?.() ?? '';
  });
}

export async function setJsonEditorValue(
  page: Page,
  testId: string,
  value: string
) {
  const locator = page.getByTestId(testId);
  await expect(locator).toBeVisible();
  await page.waitForFunction((selector) => {
    const element = document.querySelector(`[data-testid="${selector}"]`) as {
      __setJsonEditorValue?: (nextValue: string) => void;
      __isJsonEditorReady?: () => boolean;
    } | null;

    return (
      typeof element?.__setJsonEditorValue === 'function' &&
      element.__isJsonEditorReady?.() === true
    );
  }, testId);

  await locator.evaluate((element, nextValue) => {
    const target = element as {
      __setJsonEditorValue?: (v: string) => void;
    };

    if (!target.__setJsonEditorValue) {
      throw new Error('JSON editor bridge not available');
    }

    target.__setJsonEditorValue(nextValue);
  }, value);
}

export async function getJsonEditorSuggestions(
  page: Page,
  testId: string,
  lineNumber: number,
  column: number
) {
  const locator = page.getByTestId(testId);
  await expect(locator).toBeVisible();
  await page.waitForFunction((selector) => {
    const element = document.querySelector(`[data-testid="${selector}"]`) as {
      __isJsonEditorReady?: () => boolean;
      __getJsonEditorSuggestions?: (
        line: number,
        col: number
      ) => Array<{ label: string; detail?: string }>;
    } | null;

    return (
      typeof element?.__getJsonEditorSuggestions === 'function' &&
      element.__isJsonEditorReady?.() === true
    );
  }, testId);

  return locator.evaluate(
    (element, params) => {
      const target = element as {
        __getJsonEditorSuggestions?: (
          line: number,
          col: number
        ) => Array<{ label: string; detail?: string }>;
      };

      if (!target.__getJsonEditorSuggestions) {
        throw new Error('JSON editor suggestions bridge not available');
      }

      return target.__getJsonEditorSuggestions(
        params.lineNumber,
        params.column
      );
    },
    { lineNumber, column }
  );
}

export async function focusJsonEditorAt(
  page: Page,
  testId: string,
  lineNumber: number,
  column: number
) {
  const locator = page.getByTestId(testId);
  await expect(locator).toBeVisible();
  await page.waitForFunction((selector) => {
    const element = document.querySelector(`[data-testid="${selector}"]`) as {
      __isJsonEditorReady?: () => boolean;
      __focusJsonEditorAt?: (line: number, col: number) => void;
    } | null;

    return (
      typeof element?.__focusJsonEditorAt === 'function' &&
      element.__isJsonEditorReady?.() === true
    );
  }, testId);

  await locator.evaluate(
    (element, params) => {
      const target = element as {
        __focusJsonEditorAt?: (line: number, col: number) => void;
      };

      if (!target.__focusJsonEditorAt) {
        throw new Error('JSON editor focus bridge not available');
      }

      target.__focusJsonEditorAt(params.lineNumber, params.column);
    },
    { lineNumber, column }
  );
}
