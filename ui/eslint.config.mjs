import { defineConfig, globalIgnores } from 'eslint/config';
import nextVitals from 'eslint-config-next/core-web-vitals';
import simpleImportSort from 'eslint-plugin-simple-import-sort';
import unusedImports from 'eslint-plugin-unused-imports';
import tseslint from 'typescript-eslint';

const eslintConfig = defineConfig([
  ...nextVitals,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    '.next/**',
    'out/**',
    'build/**',
    'next-env.d.ts',
    // Auto-generated files
    'src/core/api/generated/**',
  ]),
  {
    plugins: {
      'simple-import-sort': simpleImportSort,
      'unused-imports': unusedImports,
      '@typescript-eslint': tseslint.plugin,
    },
    rules: {
      // Import sorting
      'simple-import-sort/imports': 'error',
      'simple-import-sort/exports': 'error',

      // Unused imports
      'unused-imports/no-unused-imports': 'error',
      'unused-imports/no-unused-vars': [
        'warn',
        {
          vars: 'all',
          varsIgnorePattern: '^_',
          args: 'after-used',
          argsIgnorePattern: '^_',
        },
      ],

      // Prefer type over interface
      '@typescript-eslint/consistent-type-definitions': ['error', 'type'],

      // Prevent leaked renders in JSX (e.g., {count && <Component />} rendering "0")
      // Requires either: ternary {x ? <C /> : null} or coercion {!!x && <C />}
      'react/jsx-no-leaked-render': [
        'error',
        { validStrategies: ['ternary', 'coerce'] },
      ],

      // Security: disallow dangerouslySetInnerHTML to avoid XSS sinks.
      'react/no-danger': 'error',

      // Security: discourage direct innerHTML assignments. React code should
      // render via JSX; if raw HTML is truly needed it should go through a
      // dedicated, reviewed sanitization layer.
      'no-restricted-properties': [
        'error',
        {
          object: '*',
          property: 'innerHTML',
          message:
            'Avoid setting innerHTML directly. Use React rendering or a reviewed sanitization helper.',
        },
      ],
    },
  },
]);

export default eslintConfig;
