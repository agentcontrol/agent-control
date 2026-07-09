import {
  Accordion,
  Alert,
  Badge,
  Box,
  Center,
  Code,
  CopyButton,
  Divider,
  Group,
  Loader,
  Modal,
  MultiSelect,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { Button } from '@rungalileo/jupiter-ds';
import {
  IconAlertCircle,
  IconCheck,
  IconCopy,
  IconKey,
  IconPlus,
  IconRefresh,
  IconShieldLock,
  IconTrash,
  IconUsers,
} from '@tabler/icons-react';
import { useMemo, useState } from 'react';

import type {
  AccessUserControlGrant,
  AccessUserResponse,
  AccessUserRole,
  ApiKeyResponse,
  CredentialSecretResponse,
} from '@/core/api/access';
import type { ControlSummary } from '@/core/api/types';
import { useAccessUsers } from '@/core/hooks/query-hooks/access/use-access-users';
import { useCreateAccessUser } from '@/core/hooks/query-hooks/access/use-create-access-user';
import { useIssueApiKey } from '@/core/hooks/query-hooks/access/use-issue-api-key';
import { useRevokeApiKey } from '@/core/hooks/query-hooks/access/use-revoke-api-key';
import { useRotateApiKey } from '@/core/hooks/query-hooks/access/use-rotate-api-key';
import { useUpdateAccessUser } from '@/core/hooks/query-hooks/access/use-update-access-user';
import { useUpdateUserControlGrants } from '@/core/hooks/query-hooks/access/use-update-user-control-grants';
import { useUserApiKeys } from '@/core/hooks/query-hooks/access/use-user-api-keys';
import { useUserControlGrants } from '@/core/hooks/query-hooks/access/use-user-control-grants';
import { useAllControls } from '@/core/hooks/query-hooks/use-controls';
import { useAuth } from '@/core/providers/auth-provider';
import { openDestructiveConfirmModal } from '@/core/utils/modals';

type SecretState = CredentialSecretResponse & {
  userName: string;
  action: 'created' | 'issued' | 'rotated';
};

type ControlOption = {
  value: string;
  label: string;
};

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return 'Never';
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? value : timestamp.toLocaleString();
}

function isActiveCredential(apiKey: ApiKeyResponse): boolean {
  if (!apiKey.enabled || apiKey.revoked_at) return false;
  return (
    !apiKey.expires_at || new Date(apiKey.expires_at).getTime() > Date.now()
  );
}

function AccessDenied() {
  return (
    <Center h="calc(100vh - 54px)" p="xl">
      <Alert
        icon={<IconShieldLock size={20} />}
        title="Administrator access required"
        color="orange"
        maw={560}
      >
        Users, credentials, and rule bucket assignments can only be managed by
        an administrator. Member access is read-only.
      </Alert>
    </Center>
  );
}

function SecretModal({
  secretState,
  onClose,
}: {
  secretState: SecretState | null;
  onClose: () => void;
}) {
  const secret = secretState?.secret ?? '';
  const defenseClawCommand = 'defenseclaw keys set AGENT_CONTROL_API_KEY';
  const title =
    secretState?.action === 'rotated'
      ? 'API key rotated'
      : secretState?.action === 'issued'
        ? 'API key issued'
        : 'User and API key created';

  return (
    <Modal
      opened={secretState !== null}
      onClose={onClose}
      title={title}
      centered
      size="lg"
      closeOnClickOutside={false}
      closeOnEscape={false}
    >
      {secretState ? (
        <Stack gap="md">
          <Alert icon={<IconKey size={18} />} color="yellow" title="Copy now">
            This secret is shown only once. It signs {secretState.userName} into
            both the UI and DefenseClaw SDK. Store it before closing.
          </Alert>

          <Group gap="xs" wrap="nowrap">
            <Code block style={{ flex: 1, overflowWrap: 'anywhere' }}>
              {secret}
            </Code>
            <CopyButton value={secret} timeout={2000}>
              {({ copied, copy }) => (
                <Tooltip label={copied ? 'Copied' : 'Copy API key'}>
                  <Button
                    variant="outline"
                    onClick={copy}
                    aria-label="Copy API key"
                    data-testid="copy-api-key"
                    leftSection={
                      copied ? <IconCheck size={16} /> : <IconCopy size={16} />
                    }
                  >
                    {copied ? 'Copied' : 'Copy'}
                  </Button>
                </Tooltip>
              )}
            </CopyButton>
          </Group>

          <Divider />

          <Stack gap="xs">
            <Text size="sm" fw={600}>
              Use with Agent Control and DefenseClaw
            </Text>
            <Text size="xs" c="dimmed">
              Use this key to sign in to Agent Control. Store the same value for
              DefenseClaw through its hidden prompt:
            </Text>
            <Group gap="xs" wrap="nowrap">
              <Code block style={{ flex: 1, overflowWrap: 'anywhere' }}>
                {defenseClawCommand}
              </Code>
              <CopyButton value={defenseClawCommand} timeout={2000}>
                {({ copied, copy }) => (
                  <Button
                    variant="outline"
                    onClick={copy}
                    aria-label="Copy DefenseClaw command"
                    data-testid="copy-defenseclaw-command"
                  >
                    {copied ? 'Copied' : 'Copy'}
                  </Button>
                )}
              </CopyButton>
            </Group>
          </Stack>

          <Group justify="flex-end">
            <Button onClick={onClose} data-testid="close-api-key-secret">
              I have stored this key
            </Button>
          </Group>
        </Stack>
      ) : null}
    </Modal>
  );
}

function CreateUserForm({
  onSecretCreated,
}: {
  onSecretCreated: (secretState: SecretState) => void;
}) {
  const createUser = useCreateAccessUser();
  const form = useForm<{ name: string; role: AccessUserRole }>({
    initialValues: { name: '', role: 'member' },
    validate: {
      name: (value) => (value.trim().length > 0 ? null : 'Enter a user name'),
    },
  });

  const handleSubmit = form.onSubmit(async (values) => {
    const name = values.name.trim();
    try {
      const created = await createUser.mutateAsync({
        name,
        role: values.role,
        enabled: true,
      });
      form.reset();
      onSecretCreated({
        api_key: created.api_key,
        secret: created.secret,
        userName: created.user.name,
        action: 'created',
      });
      notifications.show({
        color: 'green',
        title: 'User created',
        message: `${name} now has one API key for UI and SDK access.`,
      });
    } catch {
      // The inline alert below remains visible until the next attempt.
    }
  });

  return (
    <Paper withBorder p="lg" radius="md">
      <form onSubmit={handleSubmit}>
        <Stack gap="md">
          <Group gap="xs">
            <IconPlus size={18} />
            <Text fw={600}>Create user</Text>
          </Group>
          <Text size="xs" c="dimmed">
            Creating a user automatically issues their single API key. The key
            works for both the Agent Control UI and DefenseClaw SDK.
          </Text>

          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput
              label="Name"
              placeholder="DefenseClaw operator"
              required
              {...form.getInputProps('name')}
            />
            <Select
              label="Role"
              data={[
                { value: 'member', label: 'Member (assigned buckets)' },
                { value: 'admin', label: 'Administrator (unrestricted)' },
              ]}
              allowDeselect={false}
              {...form.getInputProps('role')}
            />
          </SimpleGrid>

          {createUser.isError ? (
            <Alert color="red" icon={<IconAlertCircle size={16} />}>
              The user and key could not be created. Check the name and try
              again.
            </Alert>
          ) : null}

          <Group justify="flex-end">
            <Button
              type="submit"
              loading={createUser.isPending}
              data-testid="create-access-user"
            >
              Create user and key
            </Button>
          </Group>
        </Stack>
      </form>
    </Paper>
  );
}

function LoadedGrantEditor({
  user,
  grant,
  controlOptions,
}: {
  user: AccessUserResponse;
  grant: AccessUserControlGrant;
  controlOptions: ControlOption[];
}) {
  const initialControlIds = grant.control_ids.map(String);
  const [selectedControlIds, setSelectedControlIds] =
    useState<string[]>(initialControlIds);
  const updateGrants = useUpdateUserControlGrants();
  const initialSignature = [...initialControlIds].sort().join(',');
  const selectedSignature = [...selectedControlIds].sort().join(',');

  const handleSave = async () => {
    try {
      await updateGrants.mutateAsync({
        userId: user.id,
        controlIds: selectedControlIds.map(Number),
      });
      notifications.show({
        color: 'green',
        title: 'Rule buckets updated',
        message: `${user.name} now has ${selectedControlIds.length} assigned bucket${selectedControlIds.length === 1 ? '' : 's'}.`,
      });
    } catch {
      // The inline alert below remains visible until another save succeeds.
    }
  };

  return (
    <Stack gap="xs">
      <MultiSelect
        label="Assigned rule buckets"
        description="Assignments belong to this user and survive API key rotation."
        data={controlOptions}
        value={selectedControlIds}
        onChange={setSelectedControlIds}
        placeholder={
          controlOptions.length === 0
            ? 'No rule buckets are available'
            : 'Select rule buckets'
        }
        searchable
        clearable
        disabled={!user.enabled || controlOptions.length === 0}
        nothingFoundMessage="No matching rule buckets"
        aria-label={`Assigned rule buckets for ${user.name}`}
      />

      {updateGrants.isError ? (
        <Alert color="red" icon={<IconAlertCircle size={16} />}>
          Rule bucket assignments could not be saved. Try again.
        </Alert>
      ) : null}

      <Group justify="flex-end">
        <Button
          size="sm"
          variant="outline"
          onClick={() => void handleSave()}
          loading={updateGrants.isPending}
          disabled={
            !user.enabled ||
            controlOptions.length === 0 ||
            initialSignature === selectedSignature
          }
          data-testid={`save-grants-${user.id}`}
        >
          Save assignments
        </Button>
      </Group>
    </Stack>
  );
}

function UserGrantEditor({
  user,
  controlOptions,
  controlsError,
  expanded,
}: {
  user: AccessUserResponse;
  controlOptions: ControlOption[];
  controlsError: boolean;
  expanded: boolean;
}) {
  const grants = useUserControlGrants(
    user.id,
    expanded && user.role === 'member'
  );

  if (user.role === 'admin') {
    return (
      <Alert color="violet" icon={<IconShieldLock size={16} />}>
        Administrators are namespace-wide. Rule bucket assignments do not
        restrict them.
      </Alert>
    );
  }
  if (controlsError) {
    return (
      <Alert color="red" icon={<IconAlertCircle size={16} />}>
        Rule buckets could not be loaded. Existing assignments were not changed.
      </Alert>
    );
  }
  if (grants.isLoading) {
    return (
      <Group gap="xs">
        <Loader size="xs" />
        <Text size="xs" c="dimmed">
          Loading rule bucket assignments...
        </Text>
      </Group>
    );
  }
  if (grants.isError || !grants.data) {
    return (
      <Alert color="red" icon={<IconAlertCircle size={16} />}>
        Assignments for this user could not be loaded.
      </Alert>
    );
  }

  const signature = [...grants.data.control_ids].sort().join(',');
  return (
    <LoadedGrantEditor
      key={`${user.id}:${signature}`}
      user={user}
      grant={grants.data}
      controlOptions={controlOptions}
    />
  );
}

function UserCredential({
  user,
  expanded,
  onSecretCreated,
}: {
  user: AccessUserResponse;
  expanded: boolean;
  onSecretCreated: (secretState: SecretState) => void;
}) {
  const keys = useUserApiKeys(user.id, expanded);
  const issueKey = useIssueApiKey();
  const rotateKey = useRotateApiKey();
  const revokeKey = useRevokeApiKey();
  const liveKey = keys.data?.find(isActiveCredential);
  const activeKey = user.enabled ? liveKey : undefined;
  const latestKey = keys.data?.[0];
  const previousKeyCount = Math.max((keys.data?.length ?? 0) - 1, 0);

  const showSecret = (
    created: CredentialSecretResponse,
    action: SecretState['action']
  ) => {
    onSecretCreated({ ...created, userName: user.name, action });
  };

  const handleIssue = async () => {
    try {
      const created = await issueKey.mutateAsync({ userId: user.id });
      showSecret(created, 'issued');
    } catch {
      notifications.show({
        color: 'red',
        title: 'Unable to issue API key',
        message: 'No credential was changed. Reload and try again.',
      });
    }
  };

  const handleRotate = () => {
    openDestructiveConfirmModal({
      title: 'Rotate API key?',
      confirmLabel: 'Rotate key',
      children: (
        <Text size="sm">
          The current key for <strong>{user.name}</strong> will stop working
          immediately. Their bucket assignments and enforcement history will be
          preserved.
        </Text>
      ),
      onConfirm: () => {
        rotateKey.mutate(
          { userId: user.id },
          {
            onSuccess: (created) => showSecret(created, 'rotated'),
            onError: () => {
              notifications.show({
                color: 'red',
                title: 'Unable to rotate API key',
                message: 'The existing key remains active. Try again.',
              });
            },
          }
        );
      },
    });
  };

  const handleRevoke = () => {
    openDestructiveConfirmModal({
      title: 'Revoke API key?',
      confirmLabel: 'Revoke key',
      children: (
        <Text size="sm">
          <strong>{user.name}</strong> will immediately lose UI and SDK access.
          Their bucket assignments and enforcement history will be preserved.
        </Text>
      ),
      onConfirm: () => {
        revokeKey.mutate(
          { userId: user.id },
          {
            onSuccess: () => {
              notifications.show({
                color: 'green',
                title: 'API key revoked',
                message: `${user.name} can no longer authenticate.`,
              });
            },
            onError: () => {
              notifications.show({
                color: 'red',
                title: 'Unable to revoke API key',
                message: 'No access was changed. Try again.',
              });
            },
          }
        );
      },
    });
  };

  if (keys.isLoading) {
    return (
      <Group gap="xs">
        <Loader size="xs" />
        <Text size="xs" c="dimmed">
          Loading credential...
        </Text>
      </Group>
    );
  }
  if (keys.isError) {
    return (
      <Alert color="red" icon={<IconAlertCircle size={16} />}>
        The credential state for this user could not be loaded.
      </Alert>
    );
  }

  return (
    <Paper withBorder p="md" radius="md" data-testid={`credential-${user.id}`}>
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Stack gap={3}>
            <Group gap="xs">
              <IconKey size={16} />
              <Text size="sm" fw={600}>
                API credential
              </Text>
              <Badge color={activeKey ? 'green' : 'gray'} variant="light">
                {activeKey ? 'Active' : liveKey ? 'Suspended' : 'Not active'}
              </Badge>
            </Group>
            {latestKey ? (
              <Text size="xs" c="dimmed">
                Prefix {latestKey.key_prefix} · Issued{' '}
                {formatTimestamp(latestKey.created_at)}
              </Text>
            ) : (
              <Text size="xs" c="dimmed">
                No credential has been issued.
              </Text>
            )}
            <Text size="xs" c="dimmed">
              One active key signs this user into both the UI and DefenseClaw
              SDK.
            </Text>
            {previousKeyCount > 0 ? (
              <Text size="xs" c="dimmed">
                {previousKeyCount} previous revoked credential
                {previousKeyCount === 1 ? '' : 's'} retained for audit.
              </Text>
            ) : null}
          </Stack>

          <Group gap="xs">
            {liveKey ? (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleRotate}
                  loading={rotateKey.isPending}
                  disabled={!user.enabled || revokeKey.isPending}
                  leftSection={<IconRefresh size={15} />}
                  data-testid={`rotate-api-key-${user.id}`}
                >
                  Rotate
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  color="red"
                  onClick={handleRevoke}
                  loading={revokeKey.isPending}
                  disabled={rotateKey.isPending}
                  leftSection={<IconTrash size={15} />}
                  data-testid={`revoke-api-key-${user.id}`}
                >
                  Revoke
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                onClick={() => void handleIssue()}
                loading={issueKey.isPending}
                disabled={!user.enabled}
                leftSection={<IconKey size={15} />}
                data-testid={`issue-api-key-${user.id}`}
              >
                Issue key
              </Button>
            )}
          </Group>
        </Group>
      </Stack>
    </Paper>
  );
}

function UserPanel({
  user,
  controlOptions,
  controlsError,
  onSecretCreated,
  expanded,
}: {
  user: AccessUserResponse;
  controlOptions: ControlOption[];
  controlsError: boolean;
  onSecretCreated: (secretState: SecretState) => void;
  expanded: boolean;
}) {
  const updateUser = useUpdateAccessUser();

  const update = (request: { enabled?: boolean; role?: AccessUserRole }) => {
    updateUser.mutate(
      { userId: user.id, request },
      {
        onError: () => {
          notifications.show({
            color: 'red',
            title: 'Unable to update user',
            message: 'The user state was not changed.',
          });
        },
      }
    );
  };

  return (
    <Accordion.Item value={user.id}>
      <Accordion.Control>
        <Group justify="space-between" pr="md" wrap="nowrap">
          <Stack gap={2}>
            <Text fw={600}>{user.name}</Text>
            <Text size="xs" c="dimmed">
              Created {formatTimestamp(user.created_at)}
            </Text>
          </Stack>
          <Group gap="xs" wrap="wrap" justify="flex-end">
            <Badge
              color={user.role === 'admin' ? 'violet' : 'blue'}
              variant="light"
            >
              {user.role === 'admin' ? 'Administrator' : 'Member'}
            </Badge>
            <Badge color={user.enabled ? 'green' : 'gray'} variant="light">
              {user.enabled ? 'Enabled' : 'Disabled'}
            </Badge>
          </Group>
        </Group>
      </Accordion.Control>
      <Accordion.Panel>
        <Stack gap="lg">
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="lg">
            <Select
              label="Role"
              description="Members are limited to assigned rule buckets."
              value={user.role}
              data={[
                { value: 'member', label: 'Member' },
                { value: 'admin', label: 'Administrator' },
              ]}
              allowDeselect={false}
              onChange={(value) =>
                value && update({ role: value as AccessUserRole })
              }
              disabled={updateUser.isPending}
              aria-label={`Role for ${user.name}`}
            />
            <Switch
              mt="xl"
              label="User enabled"
              description="Disabling the user immediately invalidates their key."
              checked={user.enabled}
              onChange={(event) =>
                update({ enabled: event.currentTarget.checked })
              }
              disabled={updateUser.isPending}
              aria-label={`Enable ${user.name}`}
            />
          </SimpleGrid>

          <Divider />

          {expanded ? (
            <>
              <Stack gap="xs">
                <Text size="sm" fw={600}>
                  Credential
                </Text>
                <UserCredential
                  user={user}
                  expanded={expanded}
                  onSecretCreated={onSecretCreated}
                />
              </Stack>

              <Stack gap="xs">
                <Text size="sm" fw={600}>
                  Rule bucket access
                </Text>
                <UserGrantEditor
                  user={user}
                  controlOptions={controlOptions}
                  controlsError={controlsError}
                  expanded={expanded}
                />
              </Stack>
            </>
          ) : null}
        </Stack>
      </Accordion.Panel>
    </Accordion.Item>
  );
}

function AdminAccessContent() {
  const users = useAccessUsers();
  const controls = useAllControls();
  const [expandedUserId, setExpandedUserId] = useState<string | null>(null);
  const [secretState, setSecretState] = useState<SecretState | null>(null);

  const controlOptions = useMemo<ControlOption[]>(() => {
    const options = (controls.data ?? []).map((control: ControlSummary) => ({
      value: String(control.id),
      label: control.name,
    }));
    return options.toSorted((left, right) =>
      left.label.localeCompare(right.label)
    );
  }, [controls.data]);

  return (
    <Box p="xl" maw={1100} mx="auto">
      <Stack gap="xl">
        <Group justify="space-between" align="flex-start">
          <Stack gap={4}>
            <Group gap="xs">
              <IconUsers size={24} />
              <Title order={2} fw={600}>
                Access management
              </Title>
            </Group>
            <Text size="sm" c="dimmed" maw={760}>
              Create users, rotate their single API key, and assign rule
              buckets. The same key authenticates the UI and DefenseClaw SDK;
              assignments and Monitor history remain owned by the user.
            </Text>
          </Stack>
          <Badge color="violet" variant="light" size="lg">
            Admin only
          </Badge>
        </Group>

        <CreateUserForm onSecretCreated={setSecretState} />

        <Stack gap="md">
          <Group justify="space-between">
            <Stack gap={2}>
              <Title order={3} fw={600}>
                Users
              </Title>
              <Text size="xs" c="dimmed">
                Expand a user to manage their credential and rule bucket access.
              </Text>
            </Stack>
            {users.data ? (
              <Badge variant="outline">
                {users.data.length} user{users.data.length === 1 ? '' : 's'}
              </Badge>
            ) : null}
          </Group>

          {users.isLoading ? (
            <Paper withBorder p="xl" radius="md">
              <Center py="xl">
                <Stack align="center" gap="xs">
                  <Loader size="md" />
                  <Text size="sm" c="dimmed">
                    Loading users...
                  </Text>
                </Stack>
              </Center>
            </Paper>
          ) : users.isError ? (
            <Alert
              color="red"
              icon={<IconAlertCircle size={18} />}
              title="Unable to load users"
            >
              <Stack gap="sm">
                <Text size="sm">
                  Agent Control could not load access-management data.
                </Text>
                <Box>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => void users.refetch()}
                    data-testid="retry-access-users"
                  >
                    Try again
                  </Button>
                </Box>
              </Stack>
            </Alert>
          ) : users.data?.length ? (
            <Accordion
              variant="separated"
              radius="md"
              value={expandedUserId}
              onChange={setExpandedUserId}
            >
              {users.data.map((user) => (
                <UserPanel
                  key={user.id}
                  user={user}
                  controlOptions={controlOptions}
                  controlsError={controls.isError}
                  onSecretCreated={setSecretState}
                  expanded={expandedUserId === user.id}
                />
              ))}
            </Accordion>
          ) : (
            <Paper withBorder p="xl" radius="md">
              <Center py="xl">
                <Stack align="center" gap="xs">
                  <IconUsers size={28} color="var(--mantine-color-dimmed)" />
                  <Text fw={600}>No users yet</Text>
                  <Text size="sm" c="dimmed" ta="center">
                    Create the first user to issue their UI and SDK key.
                  </Text>
                </Stack>
              </Center>
            </Paper>
          )}
        </Stack>
      </Stack>

      <SecretModal
        secretState={secretState}
        onClose={() => setSecretState(null)}
      />
    </Box>
  );
}

export default function AccessManagementPage() {
  const { auth } = useAuth();
  const canManageAccess =
    auth.status === 'not-required' ||
    (auth.status === 'authenticated' && auth.isAdmin);

  return canManageAccess ? <AdminAccessContent /> : <AccessDenied />;
}
