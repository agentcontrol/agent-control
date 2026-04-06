/**
 * `playwright` ships `jsx-runtime` at runtime (`exports["./jsx-runtime"]`) but does not
 * declare `types` for that subpath. The `@jsxImportSource playwright` pragma in CT specs
 * needs this module declaration so tsc can typecheck JSX.
 */
declare module 'playwright/jsx-runtime' {
  export { Fragment, jsx, jsxs } from 'react/jsx-runtime';
}
