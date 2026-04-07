export function removeTrailingCommasOutsideStrings(text: string): string {
  let fixed = '';
  let inString = false;
  let escaped = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];

    if (char === '"' && !escaped) {
      inString = !inString;
      fixed += char;
      continue;
    }

    if (inString) {
      escaped = char === '\\' ? !escaped : false;
      fixed += char;
      continue;
    }

    if (char === ',') {
      let lookahead = index + 1;
      while (lookahead < text.length && /\s/.test(text[lookahead] ?? '')) {
        lookahead += 1;
      }

      const next = text[lookahead];
      if (next === '}' || next === ']') {
        continue;
      }
    }

    fixed += char;
  }

  return fixed;
}
