'use client';

import {
  Accordion,
  Badge,
  Card,
  Code,
  Group,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useEffect, useRef, useState } from 'react';

import type { ControlExecutionEvent } from '@/core/hooks/query-hooks/use-agent-events';

type RecentExecutionsProps = {
  events: ControlExecutionEvent[];
  hasError?: boolean;
};

type EventMetadata = Record<string, unknown>;

function asRecord(value: unknown): EventMetadata | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as EventMetadata)
    : null;
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function executionKey(event: ControlExecutionEvent): string {
  return (
    event.control_execution_id ||
    [
      event.trace_id || 'no-trace',
      event.span_id || 'no-span',
      event.control_id,
      event.timestamp || 'no-time',
    ].join(':')
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
      <Code style={{ overflowWrap: 'anywhere' }}>{value}</Code>
    </Stack>
  );
}

export function RecentExecutions({
  events,
  hasError = false,
}: RecentExecutionsProps) {
  const latestKey = events.length > 0 ? executionKey(events[0]) : null;
  const [openValue, setOpenValue] = useState<string | null>(latestKey);
  const previousLatestRef = useRef<string | null>(latestKey);

  useEffect(() => {
    const previousLatest = previousLatestRef.current;
    if (latestKey === null) {
      setOpenValue(null);
    } else if (previousLatest === null) {
      setOpenValue(latestKey);
    } else if (previousLatest !== latestKey) {
      setOpenValue((current) =>
        current === previousLatest ? latestKey : current
      );
    }
    previousLatestRef.current = latestKey;
  }, [latestKey]);

  if (hasError) {
    return (
      <Card withBorder p="md">
        <Title order={3} size="h5">
          Recent executions
        </Title>
        <Text size="sm" c="red" mt="xs">
          Failed to load recent executions.
        </Text>
      </Card>
    );
  }

  if (events.length === 0) {
    return (
      <Card withBorder p="md">
        <Title order={3} size="h5">
          Recent executions
        </Title>
        <Text size="sm" c="dimmed" mt="xs">
          Exact control spans will appear here as they are received.
        </Text>
      </Card>
    );
  }

  return (
    <Card withBorder p="md">
      <Group justify="space-between" mb="sm">
        <Title order={3} size="h5">
          Recent executions
        </Title>
        <Text size="xs" c="dimmed">
          Latest span opens automatically
        </Text>
      </Group>
      <Accordion value={openValue} onChange={setOpenValue} variant="separated">
        {events.map((event) => {
          const metadata = (event.metadata ?? {}) as EventMetadata;
          const blockedInput = asRecord(metadata.blocked_input);
          const prompt = asString(blockedInput?.prompt);
          const rawRequestBody = asString(blockedInput?.raw_request_body);
          const verdictReason = asString(metadata.verdict_reason);
          const ruleIds = Array.isArray(metadata.rule_ids)
            ? metadata.rule_ids.filter(
                (value): value is string => typeof value === 'string'
              )
            : [];
          const requestId = asString(metadata.request_id);
          const key = executionKey(event);
          const contentUnredacted = metadata.content_unredacted === true;

          return (
            <Accordion.Item key={key} value={key}>
              <Accordion.Control>
                <Group justify="space-between" wrap="nowrap" pr="md">
                  <Stack gap={1}>
                    <Text size="sm" fw={600}>
                      {event.control_name}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {event.timestamp
                        ? new Date(event.timestamp).toLocaleString()
                        : 'Timestamp unavailable'}
                    </Text>
                  </Stack>
                  <Group gap="xs" wrap="nowrap">
                    {contentUnredacted && (
                      <Badge color="orange" variant="light">
                        Unredacted
                      </Badge>
                    )}
                    {!contentUnredacted && (
                      <Badge color="gray" variant="light">
                        Metadata only
                      </Badge>
                    )}
                    <Badge color={event.action === 'deny' ? 'red' : 'blue'}>
                      {event.action}
                    </Badge>
                  </Group>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <Stack gap="md">
                  <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
                    <Detail label="Trace ID" value={event.trace_id} />
                    <Detail label="Span ID" value={event.span_id} />
                    <Detail
                      label="Request ID"
                      value={requestId ?? 'Unavailable'}
                    />
                    <Detail
                      label="Rule IDs"
                      value={
                        ruleIds.length > 0 ? ruleIds.join(', ') : 'Unavailable'
                      }
                    />
                    <Detail label="Stage" value={event.check_stage} />
                    <Detail
                      label="Duration"
                      value={
                        event.execution_duration_ms == null
                          ? 'Unavailable'
                          : `${event.execution_duration_ms} ms`
                      }
                    />
                  </SimpleGrid>

                  {prompt && (
                    <Stack gap="xs">
                      <Group gap="xs">
                        <Text size="sm" fw={600}>
                          Blocked input
                        </Text>
                        <Badge
                          color={contentUnredacted ? 'orange' : 'gray'}
                          variant="light"
                        >
                          {contentUnredacted
                            ? 'Unredacted content'
                            : 'Redacted content'}
                        </Badge>
                      </Group>
                      <Code
                        block
                        style={{
                          whiteSpace: 'pre-wrap',
                          overflowWrap: 'anywhere',
                        }}
                      >
                        {prompt}
                      </Code>
                    </Stack>
                  )}

                  {verdictReason && (
                    <Stack gap="xs">
                      <Text size="sm" fw={600}>
                        Enforcement reason
                      </Text>
                      <Code
                        block
                        style={{
                          whiteSpace: 'pre-wrap',
                          overflowWrap: 'anywhere',
                        }}
                      >
                        {verdictReason}
                      </Code>
                    </Stack>
                  )}

                  {rawRequestBody && (
                    <Accordion variant="contained">
                      <Accordion.Item value="raw-request">
                        <Accordion.Control>Raw request body</Accordion.Control>
                        <Accordion.Panel>
                          <Code
                            block
                            style={{
                              whiteSpace: 'pre-wrap',
                              overflowWrap: 'anywhere',
                            }}
                          >
                            {rawRequestBody}
                          </Code>
                        </Accordion.Panel>
                      </Accordion.Item>
                    </Accordion>
                  )}
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          );
        })}
      </Accordion>
    </Card>
  );
}
