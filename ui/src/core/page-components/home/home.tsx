import {
  Alert,
  Badge,
  Box,
  Center,
  Group,
  Loader,
  ScrollArea,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { Table } from "@rungalileo/jupiter-ds";
import { IconAlertCircle, IconSearch } from "@tabler/icons-react";
import { type ColumnDef } from "@tanstack/react-table";
import { useRouter } from "next/router";
import { useEffect, useRef } from "react";

import type { AgentSummary } from "@/core/api/types";
import { useAgentsInfinite } from "@/core/hooks/query-hooks/use-agents-infinite";

// Extended type for table display (real API data + mock data)
interface AgentTableRow extends AgentSummary {
  // Real data from API: agent_id, agent_name, agent_description, active_controls_count

  // Mock data for demo (TODO: Add to API):
  type: string;
  requests: number;
  passRate: number;
  lastActive: string;
}

const HomePage = () => {
  const router = useRouter();
  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    error,
  } = useAgentsInfinite();

  // Ref for intersection observer
  const loadMoreRef = useRef<HTMLDivElement>(null);

  // Flatten all pages into single array
  const allAgents = data?.pages.flatMap((page) => page.agents) || [];

  // Transform API data to table format with mock data for missing fields
  // TODO: Replace with API data
  const agents: AgentTableRow[] = allAgents.map((agent, index) => ({
    ...agent,
    // Mock data until API provides:
    type: index % 2 === 0 ? "1st party" : "3rd party",
    // eslint-disable-next-line react-hooks/purity
    requests: Math.floor(Math.random() * 50000) + 10000,
    // eslint-disable-next-line react-hooks/purity
    passRate: Math.floor(Math.random() * 30) + 70, // 70-100%
    // eslint-disable-next-line react-hooks/purity
    lastActive: `${Math.floor(Math.random() * 60) + 1} mins ago`,
  }));

  // Intersection observer to load more agents when scrolling near bottom
  useEffect(() => {
    if (!loadMoreRef.current || !hasNextPage || isFetchingNextPage) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          fetchNextPage();
        }
      },
      { threshold: 0.1 }
    );

    observer.observe(loadMoreRef.current);

    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const getPassRateColor = (rate: number) => {
    if (rate >= 90) return "#059669";
    if (rate >= 70) return "#D97706";
    return "#DC2626";
  };

  const handleRowClick = (agent: AgentTableRow) => {
    router.push(`/agents/${agent.agent_id}`);
  };

  // Loading state
  if (isLoading) {
    return (
      <Box p='xl' maw={1400} mx='auto' my={0}>
        <Center h={400}>
          <Stack align='center' gap='md'>
            <Loader size='lg' />
            <Text c='dimmed'>Loading agents...</Text>
          </Stack>
        </Center>
      </Box>
    );
  }

  // Error state
  if (error) {
    return (
      <Box p='xl' maw={1400} mx='auto' my={0}>
        <Alert
          icon={<IconAlertCircle size={16} />}
          title='Error loading agents'
          color='red'
        >
          Failed to fetch agents. Please try again later.
        </Alert>
      </Box>
    );
  }

  // Define table columns (real API data + mock data)
  const columns: ColumnDef<AgentTableRow>[] = [
    // ✅ Real API data
    {
      id: "agent_name",
      header: "Agent name",
      accessorKey: "agent_name",
      cell: ({ row }: { row: any }) => (
        <Text size='sm' fw={500}>
          {row.original.agent_name}
        </Text>
      ),
    },
    // 🎨 Mock data (TODO: Add to API)
    {
      id: "type",
      header: "Type",
      accessorKey: "type",
      size: 120,
      cell: ({ row }: { row: any }) => (
        <Badge
          variant='light'
          color={row.original.type === "3rd party" ? "gray" : "blue"}
          size='sm'
          tt='uppercase'
          styles={{
            root: {
              fontWeight: 600,
              fontSize: "10px",
              padding: "4px 8px",
            },
          }}
        >
          {row.original.type}
        </Badge>
      ),
    },
    // 🎨 Mock data (TODO: Add to API)
    {
      id: "requests",
      header: "Requests",
      accessorKey: "requests",
      size: 120,
      cell: ({ row }: { row: any }) => (
        <Text size='sm'>{row.original.requests.toLocaleString()}</Text>
      ),
    },
    // ✅ Real API data
    {
      id: "activeControls",
      header: "Active controls",
      accessorKey: "active_controls_count",
      size: 140,
      cell: ({ row }: { row: any }) => (
        <Text size='sm'>{row.original.active_controls_count}</Text>
      ),
    },
    // 🎨 Mock data (TODO: Add to API)
    {
      id: "passRate",
      header: "Pass rate",
      accessorKey: "passRate",
      size: 120,
      cell: ({ row }: { row: any }) => (
        <Text size='sm' fw={500} c={getPassRateColor(row.original.passRate)}>
          {row.original.passRate}%
        </Text>
      ),
    },
    // 🎨 Mock data (TODO: Add to API)
    {
      id: "lastActive",
      header: "Last active",
      accessorKey: "lastActive",
      size: 150,
      cell: ({ row }: { row: any }) => (
        <Text size='sm' c='dimmed'>
          {row.original.lastActive}
        </Text>
      ),
    },
  ];

  return (
    <Stack
      p='xl'
      maw={1400}
      mx='auto'
      my={0}
      h='calc(100vh - 54px)' // 54px = header height
      gap={0}
    >
      {/* Header */}
      <Group justify='space-between' mb='lg'>
        <Stack gap={4}>
          <Title order={2} fw={600}>
            Agents overview
          </Title>
          <Text size='sm' c='dimmed'>
            Monitor activity and control health across all deployed agents.
          </Text>
        </Stack>

        {/* Search and Filters */}
        <TextInput
          placeholder='Search or apply filter...'
          leftSection={
            <Center>
              <IconSearch size={16} />
            </Center>
          }
        />
      </Group>

      {/* Scrollable Table Container */}
      <ScrollArea flex={1} pos='relative' mih={0} type='auto'>
        <Table
          columns={columns}
          data={agents}
          onRowClick={handleRowClick}
          highlightOnHover
          withColumnBorders
        />

        {/* Intersection observer trigger */}
        {hasNextPage && <Box ref={loadMoreRef} h={20} my={16} mx={0} />}

        {/* Loading indicator for next page */}
        {isFetchingNextPage && (
          <Center p='md'>
            <Loader size='sm' />
          </Center>
        )}
      </ScrollArea>
    </Stack>
  );
};

export default HomePage;
