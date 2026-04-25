import {
  Alert,
  Box,
  Divider,
  Grid,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
} from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { Button } from '@rungalileo/jupiter-ds';
import { IconAlertCircle, IconHistory } from '@tabler/icons-react';
import { useMemo, useState } from 'react';

import { isApiError } from '@/core/api/errors';
import type { Control, ProblemDetail } from '@/core/api/types';
import { useControlVersion } from '@/core/hooks/query-hooks/use-control-version';
import { useControlVersions } from '@/core/hooks/query-hooks/use-control-versions';
import { useRestoreControlVersion } from '@/core/hooks/query-hooks/use-restore-control-version';
import {
  openActionConfirmModal,
  openDestructiveConfirmModal,
} from '@/core/utils/modals';

import { ApiErrorAlert } from './api-error-alert';
import { ControlVersionDiff } from './control-version-diff';
import { ControlVersionList } from './control-version-list';
import {
  diffControlVersions,
  snapshotFromVersion,
} from './diff-control-version';

type ControlVersionHistoryPanelProps = {
  control: Control;
  agentId: string;
  editorIsDirty: boolean;
};

type SelectedVersion = {
  controlId: number;
  versionNum: number;
};

export function ControlVersionHistoryPanel({
  control,
  agentId,
  editorIsDirty,
}: ControlVersionHistoryPanelProps) {
  const versionsQuery = useControlVersions(control.id);
  const restoreMutation = useRestoreControlVersion();
  const [selectedVersionState, setSelectedVersionState] =
    useState<SelectedVersion | null>(null);
  const [apiError, setApiError] = useState<ProblemDetail | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const versions = useMemo(
    () => versionsQuery.data?.pages.flatMap((page) => page.versions) ?? [],
    [versionsQuery.data]
  );
  const currentVersionNum =
    versions.length > 0 ? versions[0].version_num : null;
  const selectedVersionNum =
    selectedVersionState?.controlId === control.id
      ? selectedVersionState.versionNum
      : currentVersionNum;

  const selectedVersionQuery = useControlVersion(
    control.id,
    selectedVersionNum
  );
  const predecessorVersionNum =
    selectedVersionNum != null && selectedVersionNum > 1
      ? selectedVersionNum - 1
      : null;
  const predecessorVersion = useControlVersion(
    control.id,
    predecessorVersionNum
  );
  const currentVersionQuery = useControlVersion(control.id, currentVersionNum);

  const selectedSnapshot = snapshotFromVersion(selectedVersionQuery.data);
  const predecessorSnapshot = snapshotFromVersion(predecessorVersion.data);
  const currentSnapshot = snapshotFromVersion(currentVersionQuery.data);
  const predecessorRequired = predecessorVersionNum != null;
  const selectedVersionFailed =
    selectedVersionQuery.isError ||
    (!selectedVersionQuery.isLoading && !selectedVersionQuery.data);
  const predecessorVersionFailed =
    predecessorRequired &&
    (predecessorVersion.isError ||
      (!predecessorVersion.isLoading && !predecessorVersion.data));
  const currentVersionFailed =
    currentVersionQuery.isError ||
    (!currentVersionQuery.isLoading && !currentVersionQuery.data);

  const historyDiff =
    selectedSnapshot && (!predecessorRequired || predecessorSnapshot)
      ? diffControlVersions(predecessorSnapshot, selectedSnapshot)
      : null;
  const restoreDiff =
    selectedSnapshot && currentSnapshot
      ? diffControlVersions(currentSnapshot, selectedSnapshot)
      : null;
  const isCurrentSelection =
    selectedVersionNum != null && selectedVersionNum === currentVersionNum;
  const restoreDisabled =
    !selectedSnapshot ||
    !currentSnapshot ||
    isCurrentSelection ||
    currentVersionQuery.isLoading ||
    currentVersionFailed ||
    restoreDiff == null ||
    restoreDiff.isEqual ||
    restoreMutation.isPending;

  const handleRestore = () => {
    if (!selectedVersionNum || !restoreDiff) return;

    const openRestoreConfirm = () => {
      const modalId = openActionConfirmModal({
        title: `Restore version ${selectedVersionNum}?`,
        confirmLabel: 'Restore',
        children: (
          <Stack gap="xs">
            <Text size="sm" c="dimmed">
              This overwrites the current saved control with version{' '}
              {selectedVersionNum} and records a new latest version.
            </Text>
            <Text size="sm">
              {restoreDiff.changes.length} saved field
              {restoreDiff.changes.length === 1 ? '' : 's'} will change.
            </Text>
          </Stack>
        ),
        onConfirm: () => {
          modals.close(modalId);
          executeRestore(selectedVersionNum);
        },
      });
    };

    if (editorIsDirty) {
      openDestructiveConfirmModal({
        title: 'Discard unsaved draft changes?',
        confirmLabel: 'Discard and continue',
        children: (
          <Text size="sm" c="dimmed">
            Restore replaces the saved control and discards local unsaved draft
            changes in this modal.
          </Text>
        ),
        onConfirm: openRestoreConfirm,
      });
      return;
    }

    openRestoreConfirm();
  };

  const executeRestore = async (versionNum: number) => {
    setApiError(null);
    setSuccessMessage(null);
    try {
      const result = await restoreMutation.mutateAsync({
        agentId,
        controlId: control.id,
        versionNum,
      });
      setSuccessMessage(
        `Restored version ${versionNum}. Current version is ${result?.current_version_num}.`
      );
      notifications.show({
        title: 'Control restored',
        message: `Version ${versionNum} was restored.`,
        color: 'green',
      });
    } catch (error) {
      if (isApiError(error)) {
        setApiError(error.problemDetail);
        return;
      }
      setApiError({
        type: 'about:blank',
        title: 'Error',
        status: 500,
        detail:
          error instanceof Error
            ? error.message
            : 'Failed to restore control version',
        error_code: 'UNKNOWN_ERROR',
        reason: 'Unknown',
      });
    }
  };

  if (versionsQuery.isLoading) {
    return (
      <Paper withBorder p="xl" radius="sm">
        <Group justify="center">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            Loading version history...
          </Text>
        </Group>
      </Paper>
    );
  }

  if (versionsQuery.error) {
    return (
      <Alert
        color="red"
        icon={<IconAlertCircle size={16} />}
        title="History failed to load"
      >
        Version history could not be loaded. Try again later.
      </Alert>
    );
  }

  if (versions.length === 0) {
    return (
      <Alert
        color="gray"
        icon={<IconHistory size={16} />}
        title="No versions yet"
      >
        This control does not have recorded version history.
      </Alert>
    );
  }

  return (
    <Stack gap="md">
      {successMessage ? (
        <Alert color="green" variant="light">
          {successMessage}
        </Alert>
      ) : null}
      {apiError ? (
        <ApiErrorAlert
          error={apiError}
          unmappedErrors={[]}
          onClose={() => setApiError(null)}
        />
      ) : null}

      <Grid gutter="lg">
        <Grid.Col span={{ base: 12, md: 4 }}>
          <ControlVersionList
            versions={versions}
            selectedVersionNum={selectedVersionNum}
            currentVersionNum={currentVersionNum}
            hasMore={versionsQuery.hasNextPage}
            isFetchingMore={versionsQuery.isFetchingNextPage}
            onSelect={(versionNum) => {
              setApiError(null);
              setSuccessMessage(null);
              setSelectedVersionState({ controlId: control.id, versionNum });
            }}
            onLoadMore={() => versionsQuery.fetchNextPage()}
          />
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: 8 }}>
          <Paper withBorder radius="sm" p="md">
            <Stack gap="md">
              <Group justify="space-between" align="flex-start">
                <Box>
                  <Text size="sm" fw={700}>
                    Version {selectedVersionNum}
                  </Text>
                  <Text size="xs" c="dimmed">
                    Diff against immediate predecessor
                  </Text>
                </Box>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleRestore}
                  disabled={restoreDisabled}
                  loading={restoreMutation.isPending}
                  data-testid="restore-version-button"
                >
                  Restore this version
                </Button>
              </Group>

              {isCurrentSelection ? (
                <Alert color="gray" variant="light">
                  This version is already current.
                </Alert>
              ) : restoreDiff?.isEqual ? (
                <Alert color="gray" variant="light">
                  This version matches the current saved control.
                </Alert>
              ) : currentVersionFailed ? (
                <Alert color="red" variant="light">
                  Current version could not be loaded, so restore is
                  unavailable.
                </Alert>
              ) : null}

              <Divider />

              {selectedVersionQuery.isLoading ||
              (predecessorRequired && predecessorVersion.isLoading) ? (
                <Group justify="center" py="xl">
                  <Loader size="sm" />
                  <Text size="sm" c="dimmed">
                    Loading selected version...
                  </Text>
                </Group>
              ) : selectedVersionFailed ? (
                <Alert color="red" variant="light">
                  Selected version could not be loaded.
                </Alert>
              ) : predecessorVersionFailed ? (
                <Alert color="red" variant="light">
                  Previous version could not be loaded, so the diff cannot be
                  shown.
                </Alert>
              ) : historyDiff ? (
                <ControlVersionDiff
                  diff={historyDiff}
                  beforeLabel={
                    predecessorVersionNum == null
                      ? 'No predecessor'
                      : `Version ${predecessorVersionNum}`
                  }
                  afterLabel={`Version ${selectedVersionNum}`}
                  initialVersion={predecessorVersionNum == null}
                />
              ) : (
                <Alert color="red" variant="light">
                  Selected version could not be loaded.
                </Alert>
              )}
            </Stack>
          </Paper>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
