export const controlVersionKeys = {
  lists: ['controls', 'versions'] as const,
  list: (controlId: number) =>
    [...controlVersionKeys.lists, controlId] as const,
  details: (controlId: number) => ['controls', 'version', controlId] as const,
  detail: (controlId: number, versionNum: number) =>
    [...controlVersionKeys.details(controlId), versionNum] as const,
};
