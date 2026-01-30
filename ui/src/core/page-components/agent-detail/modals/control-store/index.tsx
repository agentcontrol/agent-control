import {
  Anchor,
  Box,
  Divider,
  Group,
  Loader,
  Modal,
  Paper,
  ScrollArea,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { Button, Table } from "@rungalileo/jupiter-ds";
import { IconAlertCircle, IconSearch, IconX } from "@tabler/icons-react";
import { type ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { useMemo, useState } from "react";

import { ErrorBoundary } from "@/components/error-boundary";
import { api } from "@/core/api/client";
import type { AgentRef, ControlDefinition, ControlSummary } from "@/core/api/types";
import { useControls } from "@/core/hooks/query-hooks/use-controls";

import { AddNewControlModal } from "../add-new-control";
import { EditControlContent } from "../edit-control/edit-control-content";

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
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedControl, setSelectedControl] = useState<{
    summary: ControlSummary;
    definition: ControlDefinition;
  } | null>(null);
  const [loadingControlId, setLoadingControlId] = useState<number | null>(null);
  const [editModalOpened, setEditModalOpened] = useState(false);
  const [addNewModalOpened, setAddNewModalOpened] = useState(false);
  const { data, isLoading, error } = useControls();

  const handleUseControl = async (control: ControlSummary) => {
    setLoadingControlId(control.id);
    try {
      const { data: controlData, error: fetchError } = await api.controls.getData(control.id);
      if (fetchError || !controlData) {
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

  const filteredControls = useMemo(() => {
    const controls = data?.controls ?? [];
    if (!searchQuery.trim()) return controls;
    const query = searchQuery.toLowerCase();
    return controls.filter(
      (control) =>
        control.name.toLowerCase().includes(query) ||
        (control.description ?? "").toLowerCase().includes(query)
    );
  }, [data, searchQuery]);

  // Build a draft control for the edit modal with full evaluator config
  const draftControl = useMemo(() => {
    if (!selectedControl) return null;
    const { summary, definition } = selectedControl;
    // Sanitize name to match pattern: ^[a-zA-Z0-9][a-zA-Z0-9_-]*$
    // Replace spaces with hyphens, remove invalid characters, append -copy
    const sanitizedName = summary.name
      .replace(/\s+/g, "-") // spaces -> hyphens
      .replace(/[^a-zA-Z0-9_-]/g, ""); // remove invalid chars
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
      id: "enabled",
      header: "Enabled",
      accessorKey: "enabled",
      size: 80,
      cell: ({ row }) => (
        <Text size="sm" c={row.original.enabled ? "green" : "dimmed"}>
          {row.original.enabled ? "Yes" : "No"}
        </Text>
      ),
    },
    {
      id: "agent",
      header: "Used by",
      size: 150,
      cell: ({ row }) => {
        const agent = (row.original as ControlSummaryWithAgent).used_by_agent;
        if (!agent) {
          return <Text size="sm" c="dimmed">—</Text>;
        }
        return (
          <Anchor
            component={Link}
            href={`/agents/${agent.agent_id}`}
            size="sm"
            onClick={(e) => e.stopPropagation()}
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
            data-testid="use-control-button"
            loading={loadingControlId === row.original.id}
            onClick={() => handleUseControl(row.original)}
          >
            Use
          </Button>
        </Group>
      ),
    },
  ];

  return (
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

        {/* Search Bar */}
        <Box px="md" pt="md" pb="sm">
          <TextInput
            placeholder="Search controls..."
            leftSection={<IconSearch size={16} />}
            maw={250}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </Box>

        {/* Scrollable Table Content */}
        <Box px="md" pb="md" style={{ flex: 1, minHeight: 0 }}>
          <ScrollArea h="100%" type="auto">
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
            ) : filteredControls.length > 0 ? (
              <Table columns={columns} data={filteredControls} highlightOnHover />
            ) : (
              <Paper p="xl" withBorder radius="sm" ta="center">
                <Text c="dimmed">No controls found</Text>
              </Paper>
            )}
          </ScrollArea>
        </Box>

        {/* Footer CTA */}
        <Divider />
        <Box p="md">
          <Group justify="center" gap="xs">
            <Text size="sm" c="dimmed">
              Can&apos;t find what you&apos;re looking for?
            </Text>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setAddNewModalOpened(true)}
              data-testid="footer-new-control-button"
            >
              Create new control
            </Button>
          </Group>
        </Box>
      </Box>

      {/* Edit Control Modal */}
      <Modal
        opened={editModalOpened}
        onClose={handleEditModalClose}
        title="Create Control"
        size="xl"
        keepMounted={false}
        styles={{
          title: { fontSize: "18px", fontWeight: 600 },
          content: { maxWidth: "1200px", width: "90vw" },
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
    </Modal>
  );
}
