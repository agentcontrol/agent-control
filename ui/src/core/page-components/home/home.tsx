import {
  Alert,
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
import { useEffect, useMemo, useRef, useState } from "react";

import type { AgentSummary } from "@/core/api/types";
import { useAgentsInfinite } from "@/core/hooks/query-hooks/use-agents-infinite";

// Table row type - uses real API data
type AgentTableRow = AgentSummary;

const HomePage = () => {
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState("");
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

  // Filter agents based on search query
  const agents: AgentTableRow[] = useMemo(() => {
    if (!searchQuery.trim()) return allAgents;
    const query = searchQuery.toLowerCase();
    return allAgents.filter((agent) =>
      agent.agent_name.toLowerCase().includes(query)
    );
  }, [allAgents, searchQuery]);

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

  // Define table columns
  const columns: ColumnDef<AgentTableRow>[] = [
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
    {
      id: "activeControls",
      header: "Active controls",
      accessorKey: "active_controls_count",
      size: 140,
      cell: ({ row }: { row: any }) => (
        <Text size='sm'>{row.original.active_controls_count}</Text>
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
          placeholder='Search agents...'
          leftSection={
            <Center>
              <IconSearch size={16} />
            </Center>
          }
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.currentTarget.value)}
          w={250}
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
