import {
  Alert,
  Box,
  Center,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { Table } from "@rungalileo/jupiter-ds";
import { IconAlertCircle } from "@tabler/icons-react";
import { type ColumnDef } from "@tanstack/react-table";
import { useRouter } from "next/router";
import { useMemo } from "react";

import type { AgentSummary } from "@/core/api/types";
import { SearchInput } from "@/core/components/search-input";
import { useAgentsInfinite } from "@/core/hooks/query-hooks/use-agents-infinite";
import { useInfiniteScroll } from "@/core/hooks/use-infinite-scroll";
import { useQueryParam } from "@/core/hooks/use-query-param";

// Table row type - uses real API data
type AgentTableRow = AgentSummary;

const HomePage = () => {
  const router = useRouter();
  // Get search value for debouncing (SearchInput handles the UI and URL sync)
  const [searchQuery] = useQueryParam("search");
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
    router.push(`/agents/${agent.agent_id}`);
  };

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
        <SearchInput queryKey="search" placeholder="Search agents..." />
      </Group>

      {/* Scrollable Table Container */}
      <Box style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
        {isLoading ? (
          <Center h={400}>
            <Stack align='center' gap='md'>
              <Loader size='lg' />
              <Text c='dimmed'>Loading agents...</Text>
            </Stack>
          </Center>
        ) : error ? (
          <Alert
            icon={<IconAlertCircle size={16} />}
            title='Error loading agents'
            color='red'
          >
            Failed to fetch agents. Please try again later.
          </Alert>
        ) : (
          <>
            <Table
              columns={columns}
              data={agents}
              onRowClick={handleRowClick}
              highlightOnHover
              withColumnBorders
              maxHeight='calc(100dvh - 270px)'
            />

            {/* Intersection observer trigger for infinite scroll */}
            <div ref={sentinelRef} style={{ height: 1 }} />

            {/* Loading indicator for next page */}
            {isFetchingNextPage && (
              <Center p='md'>
                <Loader size='sm' />
              </Center>
            )}
          </>
        )}
      </Box>
    </Stack>
  );
};

export default HomePage;
