import {
  Alert,
  Center,
  Modal,
  PasswordInput,
  Stack,
  Text,
  Title,
  useMantineColorScheme,
} from '@mantine/core';
import { Button } from '@rungalileo/jupiter-ds';
import { IconAlertCircle, IconLock } from '@tabler/icons-react';
import Image from 'next/image';
import type { FormEvent } from 'react';
import { useState } from 'react';

import { useAuth } from '@/core/providers/auth-provider';

type LoginModalProps = {
  opened: boolean;
};

export function LoginModal({ opened }: LoginModalProps) {
  const { colorScheme } = useMantineColorScheme();
  const { login } = useAuth();
  const [apiKey, setApiKey] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);

    const trimmed = apiKey.trim();
    if (!trimmed) {
      setError('Please enter an API key.');
      return;
    }

    setLoading(true);
    try {
      const result = await login(trimmed);
      if (!result.authenticated) {
        setError('Invalid API key. Please check and try again.');
      }
    } catch {
      setError('Unable to reach the server. Please try again later.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={() => {}}
      withCloseButton={false}
      closeOnClickOutside={false}
      closeOnEscape={false}
      centered
      size="sm"
      overlayProps={{ backgroundOpacity: 0.6, blur: 4 }}
    >
      <form onSubmit={handleSubmit}>
        <Stack gap="lg" p="md">
          <Center>
            <Image
              src={
                colorScheme === 'dark'
                  ? '/ac-logo-dark.svg'
                  : '/ac-logo-light.svg'
              }
              alt="Agent Control"
              width={48}
              height={48}
            />
          </Center>

          <Stack gap={4} ta="center">
            <Title order={3}>Agent Control</Title>
            <Text size="sm" c="dimmed">
              Enter your API key to continue.
            </Text>
          </Stack>

          {error ? (
            <Alert
              icon={<IconAlertCircle size={16} />}
              color="red"
              variant="light"
            >
              {error}
            </Alert>
          ) : null}

          <PasswordInput
            label="API Key"
            placeholder="Enter your API key"
            value={apiKey}
            onChange={(e) => setApiKey(e.currentTarget.value)}
            leftSection={<IconLock size={16} />}
            required
            autoFocus
          />

          <Button
            type="submit"
            fullWidth
            loading={loading}
            data-testid="login-submit"
          >
            Sign in
          </Button>

          <Text size="xs" c="dimmed" ta="center">
            Contact your administrator if you don&apos;t have an API key.
          </Text>
        </Stack>
      </form>
    </Modal>
  );
}
