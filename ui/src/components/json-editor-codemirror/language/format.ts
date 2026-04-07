import {
  findNodeAtLocation,
  getLocation,
  type ParseError,
  parseTree,
} from 'jsonc-parser';

import { removeTrailingCommasOutsideStrings } from '@/components/json-editor-shared/fix-json-commas';

/**
 * Map a caret offset from JSON before a full-doc pretty-print to the matching
 * offset after, using the JSON value at `getLocation(textBefore, caretBefore).path`.
 */
export function caretAfterPrettyJsonReplace(
  textBefore: string,
  caretBefore: number,
  textAfter: string
): number | null {
  const treeBefore = parseTree(textBefore);
  const treeAfter = parseTree(textAfter);
  if (!treeBefore || !treeAfter) {
    return null;
  }

  const loc = getLocation(textBefore, caretBefore);
  if (loc.path.length === 0) {
    return null;
  }

  const nodeBefore = findNodeAtLocation(treeBefore, loc.path);
  const nodeAfter = findNodeAtLocation(treeAfter, loc.path);
  if (!nodeBefore || !nodeAfter) {
    return null;
  }

  if (nodeBefore.type === 'string' && nodeAfter.type === 'string') {
    const innerStartBefore = nodeBefore.offset + 1;
    const innerStartAfter = nodeAfter.offset + 1;
    const innerLenBefore = Math.max(0, nodeBefore.length - 2);
    const innerLenAfter = Math.max(0, nodeAfter.length - 2);
    const rel = Math.min(
      Math.max(caretBefore - innerStartBefore, 0),
      innerLenBefore
    );
    const relAfter = Math.min(rel, innerLenAfter);
    return innerStartAfter + relAfter;
  }

  const startB = nodeBefore.offset;
  const endB = nodeBefore.offset + nodeBefore.length;
  const clamped = Math.min(Math.max(caretBefore, startB), endB);
  const ratio =
    nodeBefore.length > 0 ? (clamped - startB) / nodeBefore.length : 0;
  const offsetInAfter = Math.round(ratio * nodeAfter.length);
  return Math.min(
    Math.max(nodeAfter.offset, nodeAfter.offset + offsetInAfter),
    nodeAfter.offset + nodeAfter.length
  );
}

export function tryFormat(text: string): string | null {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return null;
  }
}

export function fixJsonCommas(text: string): string {
  let fixed = removeTrailingCommasOutsideStrings(text);
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
