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

const COMPARED_DATA_FIELDS = [
  'description',
  'enabled',
  'execution',
  'scope',
  'condition',
  'action',
  'tags',
  'template',
  'template_values',
] as const;

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
  const data = snapshot?.data ?? {};
  const normalizedData: Record<string, unknown> = {};
  for (const field of COMPARED_DATA_FIELDS) {
    normalizedData[field] = data[field];
  }

  if (normalizedData.enabled === undefined) {
    normalizedData.enabled = true;
  }
  if (normalizedData.tags === undefined) {
    normalizedData.tags = [];
  }

  return {
    name: snapshot?.name ?? null,
    data: normalizedData,
  };
}

function collectChanges(
  before: Record<string, unknown>,
  after: Record<string, unknown>
): ControlVersionChange[] {
  const changes: ControlVersionChange[] = [];
  compareValue('name', before.name, after.name, changes);

  const beforeData = isRecord(before.data) ? before.data : {};
  const afterData = isRecord(after.data) ? after.data : {};
  for (const field of COMPARED_DATA_FIELDS) {
    compareValue(`data.${field}`, beforeData[field], afterData[field], changes);
  }

  return changes;
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
  if (paths.has('data.template_values'))
    summary.push('Template values changed');
  if (paths.has('data.condition')) summary.push('Condition changed');
  if (paths.has('data.action')) summary.push('Action changed');
  if (paths.has('data.scope')) summary.push('Scope changed');
  if (paths.has('data.description')) summary.push('Description changed');

  return summary.length > 0 ? summary : ['No changes'];
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
