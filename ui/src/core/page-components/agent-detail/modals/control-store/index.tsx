import {
  Anchor,
  Box,
  Divider,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { Button, Table } from "@rungalileo/jupiter-ds";
import { IconAlertCircle, IconX } from "@tabler/icons-react";
import { type ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { ErrorBoundary } from "@/components/error-boundary";
import { api } from "@/core/api/client";
import type { AgentRef, ControlDefinition, ControlSummary } from "@/core/api/types";
import { SearchInput } from "@/core/components/search-input";
import { useControlsInfinite } from "@/core/hooks/query-hooks/use-controls-infinite";
import { useInfiniteScroll } from "@/core/hooks/use-infinite-scroll";
import { useQueryParam } from "@/core/hooks/use-query-param";

import { AddNewControlModal } from "../add-new-control";
import { EditControlContent } from "../edit-control/edit-control-content";
import { sanitizeControlNamePart } from "../edit-control/utils";

// Extended ControlSummary with used_by_agent (until API types are regenerated)
type ControlSummaryWithAgent = ControlSummary & {
  used_by_agent?: AgentRef | null;
};

interface ControlStoreModalProps {
  opened: boolean;
  onClose: () => void;
  agentId: string;
}

export function ControlStoreModal({
  opened,
  onClose,
  agentId,
}: ControlStoreModalProps) {
  // Get search value for debouncing (SearchInput handles the UI and URL sync)
  const [searchQuery, setSearchQuery] = useQueryParam("store_q");
  const [debouncedSearch] = useDebouncedValue(searchQuery, 300);
  const [selectedControl, setSelectedControl] = useState<{
    summary: ControlSummary;
    definition: ControlDefinition;
  } | null>(null);
  const [loadingControlId, setLoadingControlId] = useState<number | null>(null);
  const [editModalOpened, setEditModalOpened] = useState(false);
  const [addNewModalOpened, setAddNewModalOpened] = useState(false);

  // Clear search query param when modal closes
  useEffect(() => {
    if (!opened && searchQuery) {
      setSearchQuery("");
    }
  }, [opened, searchQuery, setSearchQuery]);

  // Server-side search via name param - only fetch when modal is open
  const {
    data,
    isLoading,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useControlsInfinite({
    name: debouncedSearch || undefined,
    enabled: opened,
  });

  // Infinite scroll setup
  const { sentinelRef, scrollContainerRef } = useInfiniteScroll({
    hasNextPage: hasNextPage ?? false,
    isFetchingNextPage,
    fetchNextPage,
  });
  
  // Flatten paginated data
  const controls = useMemo(() => {
    return data?.pages.flatMap((page) => page.controls) ?? [];
  }, [data]);
  
  // Ref callback to attach to Table's scroll container when maxHeight is set
  const tableWrapperRef = useRef<HTMLDivElement>(null);
  
  // Attach scroll container ref to the Table's scroll container
  useEffect(() => {
    if (tableWrapperRef.current && controls.length > 0) {
      // Find the scrollable container (the div with overflow: auto from Table's maxHeight)
      // The Table component wraps content in a div with the "root" class when maxHeight is set
      const scrollContainer = tableWrapperRef.current.querySelector('[class*="root"]') as HTMLElement;
      if (scrollContainer) {
        // Check if it's scrollable (has overflow: auto)
        const computedStyle = window.getComputedStyle(scrollContainer);
        if (computedStyle.overflow === 'auto' || computedStyle.overflowY === 'auto') {
          (scrollContainerRef as React.MutableRefObject<HTMLElement | null>).current = scrollContainer;
          
          // Append sentinel inside the scroll container (after the table)
          if (sentinelRef.current && sentinelRef.current.parentElement !== scrollContainer) {
            scrollContainer.appendChild(sentinelRef.current);
          }
        }
      }
    }
  }, [controls.length, scrollContainerRef, sentinelRef]);

  const handleCopyControl = async (control: ControlSummary) => {
    setLoadingControlId(control.id);
    try {
      const { data: controlData, error: fetchError } = await api.controls.getData(control.id);
      if (fetchError || !controlData?.data) {
        notifications.show({
          title: "Error",
          message: "Failed to load control configuration",
          color: "red",
        });
        return;
      }
      setSelectedControl({ summary: control, definition: controlData.data });
      setEditModalOpened(true);
    } finally {
      setLoadingControlId(null);
    }
  };

  const handleEditModalClose = () => {
    setEditModalOpened(false);
    setSelectedControl(null);
  };

  const handleEditModalSuccess = () => {
    handleEditModalClose();
    onClose();
  };

  // Build a draft control for the edit modal with full evaluator config (clone: append -copy to name)
  const draftControl = useMemo(() => {
    if (!selectedControl) return null;
    const { summary, definition } = selectedControl;
    const sanitizedName = sanitizeControlNamePart(summary.name);
    return {
      id: 0,
      name: `${sanitizedName}-copy`,
      control: {
        ...definition,
        // Ensure we have the proper types
        execution: (definition.execution ?? "server") as "server" | "sdk",
        scope: {
          ...definition.scope,
          stages: (definition.scope?.stages ?? ["post"]) as ("post" | "pre")[],
        },
      },
    };
  }, [selectedControl]);

  const columns: ColumnDef<ControlSummary>[] = [
    {
      id: "enabled",
      header: "",
      accessorKey: "enabled",
      size: 40,
      cell: ({ row }) => (
        <Group justify="center">
          <Tooltip label={row.original.enabled ? "Enabled" : "Disabled"}>
            <Box
              style={{
                width: 10,
                height: 10,
                borderRadius: "50%",
                backgroundColor: row.original.enabled
                  ? "var(--mantine-color-green-6)"
                  : "var(--mantine-color-gray-5)",
              }}
            />
          </Tooltip>
        </Group>
      ),
    },
    {
      id: "name",
      header: "Name",
      accessorKey: "name",
      size: 150,
      cell: ({ row }) => (
        <Text size="sm" fw={500}>
          {row.original.name}
        </Text>
      ),
    },
    {
      id: "description",
      header: "Description",
      accessorKey: "description",
      size: 200,
      cell: ({ row }) => (
        <Tooltip label={row.original.description} withArrow disabled={!row.original.description}>
          <Text size="sm" c="dimmed" lineClamp={1}>
            {row.original.description || "—"}
          </Text>
        </Tooltip>
      ),
    },
    {
      id: "agent",
      header: "Agent",
      size: 150,
      cell: ({ row }) => {
        const agent = (row.original as ControlSummaryWithAgent).used_by_agent;
        const control = row.original;
        if (!agent) {
          return <Text size="sm" c="dimmed">—</Text>;
        }
        // Link to agent detail page with control name filter
        const href = `/agents/${agent.agent_id}?q=${encodeURIComponent(control.name)}`;
        return (
          <Anchor
            component={Link}
            href={href}
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              // Close modal when navigating to agent page
              onClose();
            }}
          >
            {agent.agent_name}
          </Anchor>
        );
      },
    },
    {
      id: "actions",
      header: "",
      size: 100,
      cell: ({ row }) => (
        <Group gap="md" justify="flex-end" wrap="nowrap">
          <Button
            variant="outline"
            size="sm"
            data-testid="copy-control-button"
            loading={loadingControlId === row.original.id}
            onClick={() => handleCopyControl(row.original)}
          >
            Copy
          </Button>
        </Group>
      ),
    },
  ];

  return (
    <>
      <Modal
        opened={opened}
        onClose={onClose}
        size="xxl"
        padding={0}
        withCloseButton={false}
        styles={{
          body: {
            padding: 0,
            width: "900px",
            height: "600px",
          },
        }}
      >
        <Box h="100%" style={{ display: "flex", flexDirection: "column" }}>
          {/* Header */}
          <Box p="md">
            <Group justify="space-between" mb="xs">
              <Title order={3} fw={600}>
                Control store
              </Title>
              <Button
                size="sm"
                onClick={onClose}
                data-testid="close-control-store-modal-button"
              >
                <IconX size={16} />
              </Button>
            </Group>
            <Text size="sm" c="dimmed">
              Browse existing controls or create a new one
            </Text>
          </Box>
          <Divider />

          {/* Search Bar + Create Control */}
          <Box px="md" pt="md" pb="sm">
            <Group justify="space-between" align="flex-end">
              <SearchInput
                queryKey="store_q"
                placeholder="Search controls..."
                w={250}
              />
              <Button
                variant="filled"
                size="sm"
                onClick={() => setAddNewModalOpened(true)}
                data-testid="footer-new-control-button"
              >
                Create Control
              </Button>
            </Group>
          </Box>

          {/* Scrollable Table Content */}
          <Box px="md" pb="md" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
            {isLoading ? (
              <Paper p="xl" ta="center" withBorder radius="sm">
                <Loader size="sm" />
              </Paper>
            ) : error ? (
              <Paper p="xl" ta="center" withBorder radius="sm">
                <Stack gap="xs" align="center">
                  <IconAlertCircle
                    size={48}
                    color="var(--mantine-color-red-5)"
                  />
                  <Text c="red">Failed to load controls</Text>
                </Stack>
              </Paper>
            ) : controls.length > 0 ? (
              <Box 
                ref={tableWrapperRef}
                style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}
              >
                <Table 
                  columns={columns} 
                  data={controls} 
                  highlightOnHover 
                  maxHeight="100%"
                />
                {/* Load more sentinel for infinite scroll - will be moved inside table's scroll container by useEffect */}
                <div ref={sentinelRef} style={{ height: 1 }} />
                {isFetchingNextPage && (
                  <Box py="md" ta="center">
                    <Loader size="sm" />
                  </Box>
                )}
              </Box>
            ) : (
              <Paper p="xl" withBorder radius="sm" ta="center">
                <Text c="dimmed">No controls found</Text>
              </Paper>
            )}
          </Box>
        </Box>
      </Modal>

      {/* Edit Control Modal */}
      <Modal
        opened={editModalOpened}
        onClose={handleEditModalClose}
        title="Create Control"
        size="xl"
        keepMounted={false}
        styles={{
          title: { fontSize: "18px", fontWeight: 600 },
          content: { maxWidth: "1400px", width: "90vw" },
        }}
      >
        <ErrorBoundary variant="modal">
          {draftControl && (
            <EditControlContent
              control={draftControl}
              agentId={agentId}
              mode="create"
              onClose={handleEditModalClose}
              onSuccess={handleEditModalSuccess}
            />
          )}
        </ErrorBoundary>
      </Modal>

      <AddNewControlModal
        opened={addNewModalOpened}
        onClose={() => setAddNewModalOpened(false)}
        agentId={agentId}
      />
    </>
  );
}
