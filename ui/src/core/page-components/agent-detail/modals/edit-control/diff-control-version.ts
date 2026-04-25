import type { GetControlVersionResponse } from '@/core/api/types';

export type ControlVersionSnapshot = {
  name: string | null;
  data: Record<string, unknown>;
};

export type ControlVersionChange = {
  path: string;
  type: 'added' | 'removed' | 'changed';
  before: unknown;
  after: unknown;
};

export type ControlVersionDiffResult = {
  changes: ControlVersionChange[];
  summary: string[];
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  isEqual: boolean;
};

export function snapshotFromVersion(
  version: GetControlVersionResponse | null | undefined
): ControlVersionSnapshot | null {
  if (!version) return null;
  const raw = version.snapshot as Record<string, unknown>;
  return {
    name: typeof raw.name === 'string' ? raw.name : null,
    data: isRecord(raw.data) ? raw.data : {},
  };
}

export function diffControlVersions(
  beforeSnapshot: ControlVersionSnapshot | null,
  afterSnapshot: ControlVersionSnapshot
): ControlVersionDiffResult {
  const before = normalizeSnapshot(beforeSnapshot);
  const after = normalizeSnapshot(afterSnapshot);
  const changes = collectChanges(before, after);

  return {
    changes,
    summary: buildSummary(changes),
    before,
    after,
    isEqual: changes.length === 0,
  };
}

export function formatDiffValue(value: unknown): string {
  if (value === undefined) return 'Not set';
  if (value === null) return 'null';
  if (typeof value === 'string') return value || 'Empty string';
  if (typeof value === 'boolean' || typeof value === 'number') {
    return String(value);
  }
  return JSON.stringify(value, null, 2);
}

function normalizeSnapshot(
  snapshot: ControlVersionSnapshot | null
): Record<string, unknown> {
  return {
    name: snapshot?.name ?? null,
    data: sortValue(snapshot?.data ?? {}),
  };
}

function collectChanges(
  before: Record<string, unknown>,
  after: Record<string, unknown>
): ControlVersionChange[] {
  const changes: ControlVersionChange[] = [];
  compareValue('name', before.name, after.name, changes);
  compareRecursive('data', before.data, after.data, changes);

  return changes;
}

function compareRecursive(
  path: string,
  before: unknown,
  after: unknown,
  changes: ControlVersionChange[]
) {
  if (stableStringify(before) === stableStringify(after)) return;

  if (isRecord(before) && isRecord(after)) {
    const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].sort();
    for (const key of keys) {
      compareRecursive(`${path}.${key}`, before[key], after[key], changes);
    }
    return;
  }

  compareValue(path, before, after, changes);
}

function compareValue(
  path: string,
  before: unknown,
  after: unknown,
  changes: ControlVersionChange[]
) {
  if (stableStringify(before) === stableStringify(after)) return;
  changes.push({
    path,
    type:
      before === undefined
        ? 'added'
        : after === undefined
          ? 'removed'
          : 'changed',
    before,
    after,
  });
}

function buildSummary(changes: ControlVersionChange[]): string[] {
  const paths = new Set(changes.map((change) => change.path));
  const summary: string[] = [];

  if (paths.has('name')) summary.push('Renamed');
  if (paths.has('data.enabled')) summary.push('Enabled toggled');
  if (paths.has('data.execution')) summary.push('Execution changed');
  if (paths.has('data.tags')) summary.push('Tags changed');
  if (hasPathOrChild(paths, 'data.template_values'))
    summary.push('Template values changed');
  if (hasPathOrChild(paths, 'data.condition')) summary.push('Condition changed');
  if (hasPathOrChild(paths, 'data.action')) summary.push('Action changed');
  if (hasPathOrChild(paths, 'data.scope')) summary.push('Scope changed');
  if (paths.has('data.description')) summary.push('Description changed');

  return summary.length > 0 ? summary : ['Other fields changed'];
}

function hasPathOrChild(paths: Set<string>, prefix: string): boolean {
  const childPrefix = `${prefix}.`;
  for (const path of paths) {
    if (path === prefix || path.startsWith(childPrefix)) {
      return true;
    }
  }
  return false;
}

function stableStringify(value: unknown): string {
  return JSON.stringify(sortValue(value));
}

function sortValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(sortValue);
  }
  if (!isRecord(value)) {
    return value;
  }
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, sortValue(value[key])])
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
