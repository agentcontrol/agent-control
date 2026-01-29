import {
  Box,
  Divider,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { Button, Table } from "@rungalileo/jupiter-ds";
import {
  IconAlertCircle,
  IconSearch,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import { type ColumnDef } from "@tanstack/react-table";
import { useMemo, useState } from "react";

import { ErrorBoundary } from "@/components/error-boundary";
import type { components } from "@/core/api/generated/api-types";
import { useDeleteEvaluatorConfig } from "@/core/hooks/query-hooks/use-delete-evaluator-config";
import { useEvaluatorConfigs } from "@/core/hooks/query-hooks/use-evaluator-configs";

import { AddNewControlModal } from "./add-new-control-modal";
import { EditControlContent } from "./edit-control";

type EvaluatorConfigItem = components["schemas"]["EvaluatorConfigItem"];

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
  const [selectedConfig, setSelectedConfig] =
    useState<EvaluatorConfigItem | null>(null);
  const [editModalOpened, setEditModalOpened] = useState(false);
  const [addNewModalOpened, setAddNewModalOpened] = useState(false);
  const deleteEvaluatorConfig = useDeleteEvaluatorConfig();
  const { data, isLoading, error } = useEvaluatorConfigs();

  const handleUseConfig = (config: EvaluatorConfigItem) => {
    setSelectedConfig(config);
    setEditModalOpened(true);
  };

  const handleEditModalClose = () => {
    setEditModalOpened(false);
    setSelectedConfig(null);
  };

  const handleEditModalSuccess = () => {
    handleEditModalClose();
    onClose();
  };

  const handleDeleteConfig = async (config: EvaluatorConfigItem) => {
    const shouldDelete = window.confirm(
      `Delete evaluator config "${config.name}"? This cannot be undone.`
    );
    if (!shouldDelete) return;

    try {
      await deleteEvaluatorConfig.mutateAsync(config.id);
      notifications.show({
        title: "Deleted",
        message: `"${config.name}" has been deleted.`,
        color: "green",
      });
    } catch (deleteError) {
      notifications.show({
        title: "Delete failed",
        message:
          deleteError instanceof Error
            ? deleteError.message
            : "Unable to delete evaluator config.",
        color: "red",
      });
    }
  };

  const filteredConfigs = useMemo(() => {
    const configs = data?.evaluator_configs ?? [];
    if (!searchQuery.trim()) return configs;
    const query = searchQuery.toLowerCase();
    return configs.filter(
      (config) =>
        config.name.toLowerCase().includes(query) ||
        config.evaluator.toLowerCase().includes(query) ||
        (config.description ?? "").toLowerCase().includes(query)
    );
  }, [data, searchQuery]);

  const draftControl = useMemo(() => {
    if (!selectedConfig) return null;
    return {
      id: 0,
      name: selectedConfig.name,
      control: {
        description: selectedConfig.description,
        enabled: true,
        execution: "server" as const,
        scope: {
          step_types: ["llm"],
          stages: ["post"] as ("post" | "pre")[],
        },
        selector: {
          path: "*",
        },
        evaluator: {
          name: selectedConfig.evaluator,
          config: selectedConfig.config,
        },
        action: { decision: "deny" as const },
      },
    };
  }, [selectedConfig]);

  const columns: ColumnDef<EvaluatorConfigItem>[] = [
    {
      id: "name",
      header: "Name",
      accessorKey: "name",
      size: 120,
      cell: ({ row }) => (
        <Group gap="xs">
          <Text size="sm" fw={500}>
            {row.original.name}
          </Text>
        </Group>
      ),
    },
    {
      id: "evaluator",
      header: "Evaluator",
      accessorKey: "evaluator",
      size: 120,
      cell: ({ row }) => <Text size="sm">{row.original.evaluator}</Text>,
    },
    {
      id: "description",
      header: "Description",
      accessorKey: "description",
      size: 200,
      cell: ({ row }) => (
        <Tooltip label={row.original.description} withArrow>
          <Text size="sm" c="dimmed" lineClamp={1}>
            {row.original.description || "—"}
          </Text>
        </Tooltip>
      ),
    },
    {
      id: "actions",
      header: "",
      size: 180,
      cell: ({ row }) => (
        <Group gap="md" justify="flex-end" wrap="nowrap">
          <Button
            variant="outline"
            size="sm"
            data-testid="use-config-button"
            onClick={() => handleUseConfig(row.original)}
          >
            Use
          </Button>
          <Tooltip label="Delete" withArrow>
            <Button
              variant="destructive"
              size="sm"
              data-testid="delete-config-button"
              onClick={() => handleDeleteConfig(row.original)}
              loading={deleteEvaluatorConfig.isPending}
            >
              <IconTrash size={14} />
            </Button>
          </Tooltip>
        </Group>
      ),
    },
  ];

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size='xxl'
      padding={0}
      withCloseButton={false}
      styles={{
        body: {
          padding: 0,
          width: "800px",
          height: "600px",
        },
      }}
    >
      <Box h="100%" style={{ display: "flex", flexDirection: "column" }}>
        {/* Header */}
        <Box p='md'>
          <Group justify='space-between' mb='xs'>
            <Title order={3} fw={600}>
              Control store
            </Title>
            <Group gap="xs">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setAddNewModalOpened(true)}
                data-testid="create-new-control-button"
              >
                New control
              </Button>
              <Button
                size="sm"
                onClick={onClose}
                data-testid="close-control-store-modal-button"
              >
                <IconX size={16} />
              </Button>
            </Group>
          </Group>
          <Text size='sm' c='dimmed'>
            Choose a saved evaluator config to create a control
          </Text>
        </Box>
        <Divider />

        {/* Content */}
        <Box p="md" style={{ flex: 1, overflow: "auto" }}>
          <Stack gap="md">
            <Group justify="space-between">
              <TextInput
                placeholder="Search templates..."
                leftSection={<IconSearch size={16} />}
                flex={1}
                maw={250}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </Group>

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
                  <Text c="red">Failed to load evaluator configs</Text>
                </Stack>
              </Paper>
            ) : filteredConfigs.length > 0 ? (
              <Table
                columns={columns}
                data={filteredConfigs}
                highlightOnHover
              />
            ) : (
              <Paper p="xl" withBorder radius="sm" ta="center">
                <Text c="dimmed">No evaluator configs found</Text>
              </Paper>
            )}
          </Stack>
        </Box>
      </Box>

      {/* Edit Control Modal */}
      <Modal
        opened={editModalOpened}
        onClose={handleEditModalClose}
        title="Create Control"
        size='xl'
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
