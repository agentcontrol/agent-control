import { type ParseError, parseTree } from 'jsonc-parser';

export function tryFormat(text: string): string | null {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return null;
  }
}

export function fixJsonCommas(text: string): string {
  let fixed = text.replace(/,(\s*[}\]])/g, '$1');
  const errors: ParseError[] = [];
  parseTree(fixed, errors);
  const commaErrors = errors
    .filter((error) => error.error === 6)
    .sort((a, b) => b.offset - a.offset);
  for (const error of commaErrors) {
    let insertAt = error.offset;
    while (insertAt > 0 && /\s/.test(fixed[insertAt - 1] ?? '')) {
      insertAt -= 1;
    }
    fixed = fixed.slice(0, insertAt) + ',' + fixed.slice(insertAt);
  }
  return fixed;
}

export function normalizeOnBlur(text: string): string | null {
  const fixed = fixJsonCommas(text);
  if (fixed === text) return null;
  return tryFormat(fixed) ? fixed : null;
}
