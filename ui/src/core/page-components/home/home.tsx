import { CodeHighlight } from '@mantine/code-highlight';
import {
  Alert,
  Anchor,
  Box,
  Center,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { Table } from '@rungalileo/jupiter-ds';
import { IconAlertCircle, IconExternalLink } from '@tabler/icons-react';
import { type ColumnDef } from '@tanstack/react-table';
import { useRouter } from 'next/router';
import { useMemo } from 'react';

import type { AgentSummary } from '@/core/api/types';
import { SearchInput } from '@/core/components/search-input';
import { useAgentsInfinite } from '@/core/hooks/query-hooks/use-agents-infinite';
import { useInfiniteScroll } from '@/core/hooks/use-infinite-scroll';
import { useQueryParam } from '@/core/hooks/use-query-param';

// Table row type - uses real API data
type AgentTableRow = AgentSummary;

function EmptyAgentsState() {
  return (
    <Center h={400}>
      <Stack align="center" gap="md" maw={600}>
        <Title order={3} fw={600}>
          No agents yet
        </Title>
        <Text size="sm" c="dimmed" ta="center">
          Get started by registering your first agent with the Python SDK. Once
          an agent connects to the control server, it will appear here.
        </Text>
        <Box w="100%">
          <CodeHighlight
            language="python"
            code={`import agent_control
from agent_control import control, ControlViolationError

agent_control.init(
    agent_name="support-agent-v1",
    agent_description="Customer Support Agent",
    server_url="http://localhost:8000",
)

@control()
async def chat(message: str) -> str:
    return await llm.generate(message)`}
          />
        </Box>
        <Anchor
          href="https://github.com/agentcontrol/agent-control/blob/main/README.md"
          target="_blank"
          size="sm"
          c="blue"
          underline="hover"
        >
          <Group gap={4} align="center">
            <Text size="sm">View docs</Text>
            <IconExternalLink size={14} />
          </Group>
        </Anchor>
      </Stack>
    </Center>
  );
}

const HomePage = () => {
  const router = useRouter();
  // Get search value for debouncing (SearchInput handles the UI and URL sync)
  const [searchQuery] = useQueryParam('search');
  const [debouncedSearch] = useDebouncedValue(searchQuery, 300);

  // Server-side search via name param
  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    error,
  } = useAgentsInfinite({
    name: debouncedSearch || undefined,
  });

  // Infinite scroll setup
  const { sentinelRef } = useInfiniteScroll({
    hasNextPage: hasNextPage ?? false,
    isFetchingNextPage,
    fetchNextPage,
  });

  // Flatten paginated data
  const agents: AgentTableRow[] = useMemo(() => {
    return data?.pages.flatMap((page) => page.agents) || [];
  }, [data]);

  const handleRowClick = (agent: AgentTableRow) => {
    router.push(`/agents/${agent.agent_name}`);
  };

  // Define table columns
  const columns: ColumnDef<AgentTableRow>[] = [
    {
      id: 'agent_name',
      header: 'Agent name',
      accessorKey: 'agent_name',
      cell: ({ row }: { row: any }) => (
        <Text size="sm" fw={500}>
          {row.original.agent_name}
        </Text>
      ),
    },
    {
      id: 'activeControls',
      header: 'Active controls',
      accessorKey: 'active_controls_count',
      size: 140,
      cell: ({ row }: { row: any }) => (
        <Text size="sm">{row.original.active_controls_count}</Text>
      ),
    },
  ];

  return (
    <Stack
      p="xl"
      maw={1400}
      mx="auto"
      my={0}
      h="calc(100vh - 54px)" // 54px = header height
      gap={0}
    >
      {/* Header */}
      <Group justify="space-between" mb="lg">
        <Stack gap={4}>
          <Title order={2} fw={600}>
            Agents overview
          </Title>
          <Text size="sm" c="dimmed">
            Monitor activity and control health across all deployed agents.
          </Text>
        </Stack>

        {/* Search and Filters */}
        <SearchInput queryKey="search" placeholder="Search agents..." />
      </Group>

      {/* Scrollable Table Container */}
      <Box
        style={{
          flex: 1,
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {isLoading ? (
          <Center h={400}>
            <Stack align="center" gap="md">
              <Loader size="lg" />
              <Text c="dimmed">Loading agents...</Text>
            </Stack>
          </Center>
        ) : error ? (
          <Alert
            icon={<IconAlertCircle size={16} />}
            title="Error loading agents"
            color="red"
          >
            Failed to fetch agents. Please try again later.
          </Alert>
        ) : agents.length === 0 ? (
          <Box mt="xl">
            <EmptyAgentsState />
          </Box>
        ) : (
          <>
            <Table
              columns={columns}
              data={agents}
              onRowClick={handleRowClick}
              highlightOnHover
              withColumnBorders
              maxHeight="calc(100dvh - 270px)"
            />

            {/* Intersection observer trigger for infinite scroll */}
            <div ref={sentinelRef} style={{ height: 1 }} />

            {/* Loading indicator for next page */}
            {isFetchingNextPage ? (
              <Center p="md">
                <Loader size="sm" />
              </Center>
            ) : null}
          </>
        )}
      </Box>
    </Stack>
  );
};

export default HomePage;
