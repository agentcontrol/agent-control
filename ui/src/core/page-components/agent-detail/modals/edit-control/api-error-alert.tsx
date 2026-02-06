import { Alert, List, Text } from '@mantine/core';
import { IconAlertCircle } from '@tabler/icons-react';

import type { ProblemDetail } from '@/core/api/types';

export type ApiErrorAlertProps = {
  /** The API error to display */
  error: ProblemDetail | null;
  /** Unmapped field errors to show in the list */
  unmappedErrors?: Array<{ field: string | null; message: string }>;
  /** Callback when the alert is dismissed */
  onClose?: () => void;
};

/**
 * Alert component for displaying API errors with field-level details
 */
export const ApiErrorAlert = ({
  error,
  unmappedErrors = [],
  onClose,
}: ApiErrorAlertProps) => {
  if (!error) return null;

  return (
    <Alert
      color="red"
      title={error.title}
      icon={<IconAlertCircle size={16} />}
      withCloseButton={!!onClose}
      onClose={onClose}
    >
      <Text size="sm">{error.detail}</Text>
      {error.hint ? (
        <Text size="xs" c="dimmed" mt={4}>
          💡 {error.hint}
        </Text>
      ) : null}
      {unmappedErrors.length > 0 && (
        <List size="sm" mt="xs" spacing={2}>
          {unmappedErrors.map((err, i) => (
            <List.Item key={i}>
              {err.field ? (
                <Text component="span" fw={500} ff="monospace" size="xs">
                  {err.field}
                </Text>
              ) : null}
              {err.field ? ': ' : null}
              {err.message}
            </List.Item>
          ))}
        </List>
      )}
    </Alert>
  );
};
