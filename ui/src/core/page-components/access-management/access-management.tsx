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
  IconShieldLock,
  IconTrash,
  IconUsers,
} from '@tabler/icons-react';
import { useMemo, useState } from 'react';

import type {
  AccessUserResponse,
  AccessUserRole,
  ApiKeyControlGrant,
  ApiKeyResponse,
  CreateApiKeyResponse,
} from '@/core/api/access';
import type { ControlSummary } from '@/core/api/types';
import { useAccessUsers } from '@/core/hooks/query-hooks/access/use-access-users';
import { useApiKeyControlGrants } from '@/core/hooks/query-hooks/access/use-api-key-control-grants';
import { useCreateAccessUser } from '@/core/hooks/query-hooks/access/use-create-access-user';
import { useCreateApiKey } from '@/core/hooks/query-hooks/access/use-create-api-key';
import { useRevokeApiKey } from '@/core/hooks/query-hooks/access/use-revoke-api-key';
import { useUpdateAccessUser } from '@/core/hooks/query-hooks/access/use-update-access-user';
import { useUpdateApiKeyControlGrants } from '@/core/hooks/query-hooks/access/use-update-api-key-control-grants';
import { useUserApiKeys } from '@/core/hooks/query-hooks/access/use-user-api-keys';
import { useControls } from '@/core/hooks/query-hooks/use-controls';
import { useAuth } from '@/core/providers/auth-provider';
import { openDestructiveConfirmModal } from '@/core/utils/modals';

type SecretState = CreateApiKeyResponse & {
  userName: string;
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

function AccessDenied() {
  return (
    <Center h="calc(100vh - 54px)" p="xl">
      <Alert
        icon={<IconShieldLock size={20} />}
        title="Administrator access required"
        color="orange"
        maw={560}
      >
        API keys, users, and rule bucket assignments can only be managed by an
        administrator. Your API key remains read-only.
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

  return (
    <Modal
      opened={secretState !== null}
      onClose={onClose}
      title="API key created"
      centered
      size="lg"
      closeOnClickOutside={false}
    >
      {secretState ? (
        <Stack gap="md">
          <Alert icon={<IconKey size={18} />} color="yellow" title="Copy now">
            This secret is shown only once. Store it in a secrets manager before
            closing this dialog.
          </Alert>

          <Stack gap={6}>
            <Text size="sm" fw={500}>
              {secretState.api_key.name} for {secretState.userName}
            </Text>
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
                        copied ? (
                          <IconCheck size={16} />
                        ) : (
                          <IconCopy size={16} />
                        )
                      }
                    >
                      {copied ? 'Copied' : 'Copy'}
                    </Button>
                  </Tooltip>
                )}
              </CopyButton>
            </Group>
          </Stack>

          <Divider />

          <Stack gap="xs">
            <Text size="sm" fw={600}>
              Use with the Agent Control SDK
            </Text>
            <Text size="xs" c="dimmed">
              Inject the copied key through your secret manager under this
              environment-variable name. Do not put the secret in shell history
              or process arguments.
            </Text>
            <Code block>AGENT_CONTROL_API_KEY</Code>
          </Stack>

          <Stack gap="xs">
            <Text size="sm" fw={600}>
              Store with DefenseClaw
            </Text>
            <Text size="xs" c="dimmed">
              Run this command, then paste the key at DefenseClaw&apos;s hidden
              prompt. The secret is not placed in shell history or process
              arguments.
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

function CreateUserForm() {
  const createUser = useCreateAccessUser();
  const form = useForm<{ name: string; role: AccessUserRole }>({
    initialValues: { name: '', role: 'member' },
    validate: {
      name: (value) => (value.trim().length > 0 ? null : 'Enter a user name'),
    },
  });

  const handleSubmit = form.onSubmit(async (values) => {
    try {
      await createUser.mutateAsync({
        name: values.name.trim(),
        role: values.role,
        enabled: true,
      });
      form.reset();
      notifications.show({
        color: 'green',
        title: 'User created',
        message: `${values.name.trim()} can now receive an API key.`,
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
                { value: 'member', label: 'Member (read-only)' },
                { value: 'admin', label: 'Administrator' },
              ]}
              allowDeselect={false}
              {...form.getInputProps('role')}
            />
          </SimpleGrid>

          {createUser.isError ? (
            <Alert color="red" icon={<IconAlertCircle size={16} />}>
              The user could not be created. Check the name and try again.
            </Alert>
          ) : null}

          <Group justify="flex-end">
            <Button
              type="submit"
              loading={createUser.isPending}
              data-testid="create-access-user"
            >
              Create user
            </Button>
          </Group>
        </Stack>
      </form>
    </Paper>
  );
}

function LoadedGrantEditor({
  apiKey,
  grant,
  controlOptions,
}: {
  apiKey: ApiKeyResponse;
  grant: ApiKeyControlGrant;
  controlOptions: ControlOption[];
}) {
  const initialControlIds = grant.control_ids.map(String);
  const [selectedControlIds, setSelectedControlIds] =
    useState<string[]>(initialControlIds);
  const updateGrants = useUpdateApiKeyControlGrants();
  const initialSignature = [...initialControlIds].sort().join(',');
  const selectedSignature = [...selectedControlIds].sort().join(',');
  const isRevoked = Boolean(apiKey.revoked_at) || !apiKey.enabled;

  const handleSave = async () => {
    try {
      await updateGrants.mutateAsync({
        apiKeyId: apiKey.id,
        controlIds: selectedControlIds.map(Number),
      });
      notifications.show({
        color: 'green',
        title: 'Rule buckets updated',
        message: `${apiKey.name} now has ${selectedControlIds.length} assigned bucket${selectedControlIds.length === 1 ? '' : 's'}.`,
      });
    } catch {
      // The inline alert below remains visible until another save succeeds.
    }
  };

  return (
    <Stack gap="xs">
      <MultiSelect
        label="Assigned rule buckets"
        description="This key can download these controls and view only their execution history."
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
        disabled={isRevoked || controlOptions.length === 0}
        nothingFoundMessage="No matching rule buckets"
        aria-label={`Assigned rule buckets for ${apiKey.name}`}
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
            isRevoked ||
            controlOptions.length === 0 ||
            initialSignature === selectedSignature
          }
          data-testid={`save-grants-${apiKey.id}`}
        >
          Save assignments
        </Button>
      </Group>
    </Stack>
  );
}

function GrantEditor({
  apiKey,
  controlOptions,
  controlsError,
}: {
  apiKey: ApiKeyResponse;
  controlOptions: ControlOption[];
  controlsError: boolean;
}) {
  const isRevoked = Boolean(apiKey.revoked_at) || !apiKey.enabled;
  const grants = useApiKeyControlGrants(apiKey.id, !isRevoked);

  if (isRevoked) {
    return (
      <Text size="xs" c="dimmed">
        Rule bucket assignments are locked because this key is revoked.
      </Text>
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
        Assignments for this key could not be loaded.
      </Alert>
    );
  }

  const grantSignature = [...grants.data.control_ids].sort().join(',');
  return (
    <LoadedGrantEditor
      key={`${apiKey.id}:${grantSignature}`}
      apiKey={apiKey}
      grant={grants.data}
      controlOptions={controlOptions}
    />
  );
}

function ApiKeyCard({
  apiKey,
  userId,
  controlOptions,
  controlsError,
}: {
  apiKey: ApiKeyResponse;
  userId: string;
  controlOptions: ControlOption[];
  controlsError: boolean;
}) {
  const revokeKey = useRevokeApiKey();
  const isRevoked = Boolean(apiKey.revoked_at) || !apiKey.enabled;

  const handleRevoke = () => {
    openDestructiveConfirmModal({
      title: 'Revoke API key?',
      confirmLabel: 'Revoke key',
      children: (
        <Text size="sm">
          <strong>{apiKey.name}</strong> will immediately lose SDK and UI
          access. This cannot be undone.
        </Text>
      ),
      onConfirm: () => {
        revokeKey.mutate(
          { apiKeyId: apiKey.id, userId },
          {
            onSuccess: () => {
              notifications.show({
                color: 'green',
                title: 'API key revoked',
                message: `${apiKey.name} can no longer authenticate.`,
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

  return (
    <Paper withBorder p="md" radius="md" data-testid={`api-key-${apiKey.id}`}>
      <Stack gap="md">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Group gap="xs">
              <IconKey size={16} />
              <Text size="sm" fw={600}>
                {apiKey.name}
              </Text>
              <Badge color={isRevoked ? 'gray' : 'green'} variant="light">
                {isRevoked ? 'Revoked' : 'Active'}
              </Badge>
            </Group>
            <Text size="xs" c="dimmed">
              Prefix {apiKey.key_prefix} · Created{' '}
              {formatTimestamp(apiKey.created_at)}
            </Text>
            {apiKey.expires_at ? (
              <Text size="xs" c="dimmed">
                Expires {formatTimestamp(apiKey.expires_at)}
              </Text>
            ) : null}
          </Stack>

          <Button
            size="sm"
            variant="outline"
            color="red"
            onClick={handleRevoke}
            loading={revokeKey.isPending}
            disabled={isRevoked}
            leftSection={<IconTrash size={15} />}
            aria-label={`Revoke ${apiKey.name}`}
            data-testid={`revoke-api-key-${apiKey.id}`}
          >
            Revoke
          </Button>
        </Group>

        <Divider />

        <GrantEditor
          apiKey={apiKey}
          controlOptions={controlOptions}
          controlsError={controlsError}
        />
      </Stack>
    </Paper>
  );
}

function UserApiKeys({
  user,
  controlOptions,
  controlsError,
  onSecretCreated,
}: {
  user: AccessUserResponse;
  controlOptions: ControlOption[];
  controlsError: boolean;
  onSecretCreated: (secretState: SecretState) => void;
}) {
  const keys = useUserApiKeys(user.id);
  const createKey = useCreateApiKey();
  const [keyName, setKeyName] = useState('');

  const handleCreateKey = async () => {
    const trimmedName = keyName.trim();
    if (!trimmedName) return;

    try {
      const created = await createKey.mutateAsync({
        userId: user.id,
        request: { name: trimmedName },
      });
      setKeyName('');
      onSecretCreated({ ...created, userName: user.name });
    } catch {
      // The inline alert below remains visible until the next attempt.
    }
  };

  return (
    <Stack gap="lg">
      <Paper
        withBorder
        p="md"
        radius="md"
        bg="var(--mantine-color-default-hover)"
      >
        <Stack gap="sm">
          <Text size="sm" fw={600}>
            Create API key
          </Text>
          <Text size="xs" c="dimmed">
            The generated key signs this user into the read-only monitor and
            authenticates Agent Control SDK requests.
          </Text>
          <Group align="flex-end" wrap="wrap">
            <TextInput
              label="Key name"
              placeholder="DefenseClaw production"
              value={keyName}
              onChange={(event) => setKeyName(event.currentTarget.value)}
              disabled={!user.enabled}
              flex={1}
              miw={220}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  void handleCreateKey();
                }
              }}
            />
            <Button
              onClick={() => void handleCreateKey()}
              loading={createKey.isPending}
              disabled={!user.enabled || keyName.trim().length === 0}
              leftSection={<IconKey size={16} />}
              data-testid={`create-api-key-${user.id}`}
            >
              Generate key
            </Button>
          </Group>
          {!user.enabled ? (
            <Text size="xs" c="orange">
              Enable this user before creating another key.
            </Text>
          ) : null}
          {createKey.isError ? (
            <Alert color="red" icon={<IconAlertCircle size={16} />}>
              The API key could not be generated. Try again.
            </Alert>
          ) : null}
        </Stack>
      </Paper>

      {keys.isLoading ? (
        <Center py="xl">
          <Stack align="center" gap="xs">
            <Loader size="sm" />
            <Text size="xs" c="dimmed">
              Loading API keys...
            </Text>
          </Stack>
        </Center>
      ) : keys.isError ? (
        <Alert color="red" icon={<IconAlertCircle size={16} />}>
          API keys for this user could not be loaded.
        </Alert>
      ) : keys.data?.length ? (
        <Stack gap="sm">
          {keys.data.map((apiKey) => (
            <ApiKeyCard
              key={apiKey.id}
              apiKey={apiKey}
              userId={user.id}
              controlOptions={controlOptions}
              controlsError={controlsError}
            />
          ))}
        </Stack>
      ) : (
        <Center py="xl">
          <Stack align="center" gap={4}>
            <IconKey size={24} color="var(--mantine-color-dimmed)" />
            <Text size="sm" fw={500}>
              No API keys
            </Text>
            <Text size="xs" c="dimmed" ta="center">
              Generate a key to grant this user SDK and monitor access.
            </Text>
          </Stack>
        </Center>
      )}
    </Stack>
  );
}

function UserPanel({
  user,
  controlOptions,
  controlsError,
  onSecretCreated,
}: {
  user: AccessUserResponse;
  controlOptions: ControlOption[];
  controlsError: boolean;
  onSecretCreated: (secretState: SecretState) => void;
}) {
  const updateUser = useUpdateAccessUser();

  const handleEnabledChange = (enabled: boolean) => {
    updateUser.mutate(
      { userId: user.id, request: { enabled } },
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
          <Group justify="space-between">
            <Stack gap={2}>
              <Text size="sm" fw={600}>
                User access
              </Text>
              <Text size="xs" c="dimmed">
                Disabling a user invalidates all of their API keys.
              </Text>
            </Stack>
            <Switch
              label="Enabled"
              checked={user.enabled}
              onChange={(event) =>
                handleEnabledChange(event.currentTarget.checked)
              }
              disabled={updateUser.isPending}
              aria-label={`Enable ${user.name}`}
            />
          </Group>
          <Divider />
          <UserApiKeys
            user={user}
            controlOptions={controlOptions}
            controlsError={controlsError}
            onSecretCreated={onSecretCreated}
          />
        </Stack>
      </Accordion.Panel>
    </Accordion.Item>
  );
}

function AdminAccessContent() {
  const users = useAccessUsers();
  const controls = useControls({ limit: 100 });
  const [secretState, setSecretState] = useState<SecretState | null>(null);

  const controlOptions = useMemo<ControlOption[]>(() => {
    const summaries = (controls.data?.controls ?? []) as ControlSummary[];
    return summaries.map((control) => ({
      value: String(control.id),
      label: control.name,
    }));
  }, [controls.data?.controls]);

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
            <Text size="sm" c="dimmed" maw={720}>
              Create users, issue API keys, and choose which rule buckets each
              key can download and monitor. Members cannot change rule
              definitions or assignments.
            </Text>
          </Stack>
          <Badge color="violet" variant="light" size="lg">
            Admin only
          </Badge>
        </Group>

        <CreateUserForm />

        <Stack gap="md">
          <Group justify="space-between">
            <Stack gap={2}>
              <Title order={3} fw={600}>
                Users and API keys
              </Title>
              <Text size="xs" c="dimmed">
                Expand a user to manage credentials and rule bucket access.
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
            <Accordion variant="separated" radius="md">
              {users.data.map((user) => (
                <UserPanel
                  key={user.id}
                  user={user}
                  controlOptions={controlOptions}
                  controlsError={controls.isError}
                  onSecretCreated={setSecretState}
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
                    Create the first member, then generate an API key for their
                    SDK and monitor access.
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
