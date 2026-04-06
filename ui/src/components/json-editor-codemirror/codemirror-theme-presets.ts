import {
  defaultHighlightStyle,
  syntaxHighlighting,
} from '@codemirror/language';
import { type Extension } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import {
  atomone,
  darcula,
  dracula,
  eclipse,
  githubDark,
  githubLight,
  gruvboxDark,
  gruvboxLight,
  monokai,
  nord,
  quietlight,
  solarizedDark,
  solarizedLight,
  tokyoNight,
  tokyoNightDay,
  tokyoNightStorm,
  vscodeDark,
  vscodeLight,
  whiteLight,
} from '@uiw/codemirror-themes-all';

export const CODE_MIRROR_THEME_STORAGE_KEY =
  'agent-control.jsonEditor.cmTheme.v1';

export const DEFAULT_DARK_THEME_ID = 'vscode-dark';
export const DEFAULT_LIGHT_THEME_ID = 'mantine-light';

const LIGHT_CHROME_THEME = EditorView.theme({
  '&': {
    backgroundColor: 'var(--mantine-color-body)',
    color: 'var(--mantine-color-text)',
  },
  '.cm-gutters': {
    backgroundColor: 'var(--mantine-color-body)',
    borderRightColor: 'var(--mantine-color-body)',
    color: 'var(--mantine-color-dimmed)',
  },
  '.cm-content': {
    caretColor: 'var(--mantine-color-text)',
  },
  '.cm-cursor, .cm-dropCursor': {
    borderLeftColor: 'var(--mantine-color-text)',
  },
});

/** Light preset matching Mantine surface colors + default token palette. */
export const mantineLightCodeMirrorTheme: Extension[] = [
  LIGHT_CHROME_THEME,
  syntaxHighlighting(defaultHighlightStyle),
];

export type CodeMirrorThemePreset = {
  label: string;
  extension: Extension | Extension[];
};

export const CODE_MIRROR_DARK_THEME_PRESETS: Record<
  string,
  CodeMirrorThemePreset
> = {
  [DEFAULT_DARK_THEME_ID]: {
    label: 'VS Code Dark',
    extension: vscodeDark,
  },
  'github-dark': { label: 'GitHub Dark', extension: githubDark },
  'tokyo-night': { label: 'Tokyo Night', extension: tokyoNight },
  'tokyo-night-storm': {
    label: 'Tokyo Night Storm',
    extension: tokyoNightStorm,
  },
  nord: { label: 'Nord', extension: nord },
  dracula: { label: 'Dracula', extension: dracula },
  monokai: { label: 'Monokai', extension: monokai },
  'gruvbox-dark': { label: 'Gruvbox Dark', extension: gruvboxDark },
  darcula: { label: 'Darcula', extension: darcula },
  'atom-one': { label: 'Atom One', extension: atomone },
  'solarized-dark': { label: 'Solarized Dark', extension: solarizedDark },
};

export const CODE_MIRROR_LIGHT_THEME_PRESETS: Record<
  string,
  CodeMirrorThemePreset
> = {
  [DEFAULT_LIGHT_THEME_ID]: {
    label: 'Mantine (match app)',
    extension: mantineLightCodeMirrorTheme,
  },
  'vscode-light': { label: 'VS Code Light', extension: vscodeLight },
  'github-light': { label: 'GitHub Light', extension: githubLight },
  'tokyo-night-day': { label: 'Tokyo Night Day', extension: tokyoNightDay },
  'quiet-light': { label: 'Quiet Light', extension: quietlight },
  eclipse: { label: 'Eclipse', extension: eclipse },
  white: { label: 'White', extension: whiteLight },
  'gruvbox-light': { label: 'Gruvbox Light', extension: gruvboxLight },
  'solarized-light': { label: 'Solarized Light', extension: solarizedLight },
};

export type StoredCodeMirrorThemePrefs = {
  dark: string;
  light: string;
};

export function readStoredCodeMirrorThemePrefs(): StoredCodeMirrorThemePrefs {
  const fallback: StoredCodeMirrorThemePrefs = {
    dark: DEFAULT_DARK_THEME_ID,
    light: DEFAULT_LIGHT_THEME_ID,
  };
  if (typeof window === 'undefined') {
    return fallback;
  }
  try {
    const raw = window.localStorage.getItem(CODE_MIRROR_THEME_STORAGE_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<StoredCodeMirrorThemePrefs>;
    return {
      dark:
        parsed.dark &&
        Object.prototype.hasOwnProperty.call(
          CODE_MIRROR_DARK_THEME_PRESETS,
          parsed.dark
        )
          ? parsed.dark
          : DEFAULT_DARK_THEME_ID,
      light:
        parsed.light &&
        Object.prototype.hasOwnProperty.call(
          CODE_MIRROR_LIGHT_THEME_PRESETS,
          parsed.light
        )
          ? parsed.light
          : DEFAULT_LIGHT_THEME_ID,
    };
  } catch {
    return fallback;
  }
}

export function writeStoredCodeMirrorThemePrefs(
  prefs: StoredCodeMirrorThemePrefs
): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(
      CODE_MIRROR_THEME_STORAGE_KEY,
      JSON.stringify(prefs)
    );
  } catch {
    /* ignore quota / private mode */
  }
}
