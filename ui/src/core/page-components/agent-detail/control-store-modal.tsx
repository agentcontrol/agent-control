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
import { Button, Table } from "@rungalileo/jupiter-ds";
import {
  IconAlertCircle,
  IconSearch,
  IconSettings,
  IconSparkles,
  IconX,
} from "@tabler/icons-react";
import { type ColumnDef } from "@tanstack/react-table";
import { useMemo, useState } from "react";

import type { Control, PluginInfo } from "@/core/api/types";
import { useAddControlToAgent } from "@/core/hooks/query-hooks/use-add-control-to-agent";
import { usePlugins } from "@/core/hooks/query-hooks/use-plugins";

import { EditControl } from "./edit-control";

type PluginWithId = PluginInfo & { id: string };

/**
 * Default evaluator configs for each plugin type
 * Based on backend models in agent_control_models/controls.py
 */
const DEFAULT_PLUGIN_CONFIGS: Record<string, Record<string, unknown>> = {
  regex: {
    pattern: "^.*$",
  },
  list: {
    values: [],
    logic: "any",
    match_on: "match",
    match_mode: "exact",
    case_sensitive: false,
  },
};

function getDefaultConfigForPlugin(pluginId: string): Record<string, unknown> {
  return DEFAULT_PLUGIN_CONFIGS[pluginId] ?? {};
}

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
  const [selectedSource, setSelectedSource] = useState<"galileo" | "custom">(
    "galileo"
  );
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedPlugin, setSelectedPlugin] = useState<PluginWithId | null>(
    null
  );
  const [editModalOpened, setEditModalOpened] = useState(false);
  const { data: pluginsData, isLoading, error } = usePlugins();
  const addControlToAgent = useAddControlToAgent();

  const handleAddClick = (plugin: PluginWithId) => {
    setSelectedPlugin(plugin);
    setEditModalOpened(true);
  };

  const handleEditModalClose = () => {
    setEditModalOpened(false);
    setSelectedPlugin(null);
  };

  const handleEditModalSave = (data: Control) => {
    addControlToAgent.mutate(
      {
        agentId,
        controlName: data.name,
        definition: data.control,
      },
      {
        onSuccess: () => {
          handleEditModalClose();
          onClose();
        },
        onError: (err) => {
          console.error("Failed to add control to agent:", err);
        },
      }
    );
  };

  // Transform plugins record to array for table display
  const plugins = useMemo(() => {
    if (!pluginsData) return [];
    return Object.entries(pluginsData).map(([key, plugin]) => ({
      ...plugin,
      id: key,
    }));
  }, [pluginsData]);

  const columns: ColumnDef<PluginInfo & { id: string }>[] = [
    {
      id: "name",
      header: "Name",
      accessorKey: "name",
      size: 80,
      cell: ({ row }) => (
        <Group gap='xs'>
          <Text size='sm' fw={500}>
            {row.original.name}
          </Text>
        </Group>
      ),
    },
    {
      id: "version",
      header: "Version",
      accessorKey: "version",
      size: 80,
      cell: ({ row }) => <Text size='sm'>{row.original.version}</Text>,
    },
    {
      id: "description",
      header: "Description",
      accessorKey: "description",
      size: 200,
      cell: ({ row }) => (
        <Tooltip label={row.original.description} withArrow>
          <Text size='sm' c='dimmed' lineClamp={1}>
            {row.original.description}
          </Text>
        </Tooltip>
      ),
    },
    {
      id: "actions",
      header: "",
      size: 80,
      cell: ({ row }) => (
        <Button
          variant='outline'
          size='sm'
          data-testid='add-control-button'
          onClick={() => handleAddClick(row.original)}
        >
          Add
        </Button>
      ),
    },
  ];

  const filteredPlugins =
    selectedSource === "galileo"
      ? plugins.filter((plugin) =>
          plugin.name.toLowerCase().includes(searchQuery.toLowerCase())
        )
      : [];

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
        },
      }}
    >
      <Box>
        {/* Header */}
        <Box p='md'>
          <Group justify='space-between' mb='xs'>
            <Title order={3} fw={600}>
              Control store
            </Title>
            <Button
              size='sm'
              onClick={onClose}
              data-testid='close-control-store-modal-button'
            >
              <IconX size={16} />
            </Button>
          </Group>
          <Text size='sm' c='dimmed'>
            Browse and add controls to your agent
          </Text>
        </Box>
        <Divider />

        {/* Content */}
        <Group align='stretch' gap={0} mih={500}>
          {/* Left Sidebar */}
          <Box w={175} p='md'>
            <Stack gap='lg'>
              <Stack gap='xs'>
                <Text size='xs' fw={600} c='dimmed' tt='uppercase'>
                  Source
                </Text>
                <Stack gap={4}>
                  <Paper
                    component='button'
                    type='button'
                    onClick={() => setSelectedSource("galileo")}
                    w='100%'
                    p='xs'
                    radius='sm'
                    withBorder
                    bg={
                      selectedSource === "galileo"
                        ? "var(--mantine-color-blue-0)"
                        : "transparent"
                    }
                  >
                    <Group gap='xs'>
                      <IconSparkles
                        size={18}
                        color={
                          selectedSource === "galileo"
                            ? "var(--mantine-color-dark-9)"
                            : "var(--mantine-color-gray-2)"
                        }
                      />
                      <Text
                        size='sm'
                        fw={selectedSource === "galileo" ? 600 : 400}
                        c={selectedSource === "galileo" ? "dark" : "gray.2"}
                      >
                        OOB standard
                      </Text>
                    </Group>
                  </Paper>
                  <Paper
                    component='button'
                    type='button'
                    onClick={() => setSelectedSource("custom")}
                    w='100%'
                    p='xs'
                    radius='sm'
                    withBorder
                    bg={
                      selectedSource === "custom"
                        ? "var(--mantine-color-blue-0)"
                        : "transparent"
                    }
                  >
                    <Group gap='xs'>
                      <IconSettings
                        size={18}
                        color={
                          selectedSource === "custom"
                            ? "var(--mantine-color-dark-9)"
                            : "var(--mantine-color-gray-2)"
                        }
                      />
                      <Text
                        size='sm'
                        fw={selectedSource === "custom" ? 600 : 400}
                        c={selectedSource === "custom" ? "dark" : "gray.2"}
                      >
                        Custom
                      </Text>
                    </Group>
                  </Paper>
                </Stack>
              </Stack>
            </Stack>
          </Box>
          <Divider orientation='vertical' />

          {/* Right Content */}
          <Box flex={1} p='md'>
            <Stack gap='md'>
              {/* Search and Docs Link */}
              <Group justify='space-between'>
                <TextInput
                  placeholder='Search or apply filter...'
                  leftSection={<IconSearch size={16} />}
                  flex={1}
                  maw={250}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
                <Text size='sm' c='dimmed'>
                  Looking to add custom control?{" "}
                  <Text component='a' href='#' c='blue' size='sm' td='none'>
                    Check our Docs ↗
                  </Text>
                </Text>
              </Group>

              {/* Table or Empty State */}
              {selectedSource === "galileo" ? (
                isLoading ? (
                  <Paper p='xl' ta='center' withBorder radius='sm'>
                    <Loader size='sm' />
                  </Paper>
                ) : error ? (
                  <Paper p='xl' ta='center' withBorder radius='sm'>
                    <Stack gap='xs' align='center'>
                      <IconAlertCircle
                        size={48}
                        color='var(--mantine-color-red-5)'
                      />
                      <Text c='red'>Failed to load plugins</Text>
                    </Stack>
                  </Paper>
                ) : filteredPlugins.length > 0 ? (
                  <Table
                    columns={columns}
                    data={filteredPlugins}
                    highlightOnHover
                  />
                ) : (
                  <Paper p='xl' withBorder radius='sm' ta='center'>
                    <Text c='dimmed'>No plugins found</Text>
                  </Paper>
                )
              ) : (
                <Paper p='xl' withBorder radius='sm' ta='center'>
                  <Stack gap='xs' align='center'>
                    <IconSettings
                      size={48}
                      color='var(--mantine-color-gray-4)'
                    />
                    <Text fw={500} c='dimmed'>
                      No custom controls yet
                    </Text>
                    <Text size='sm' c='dimmed'>
                      Create your first custom control to get started
                    </Text>
                  </Stack>
                </Paper>
              )}
            </Stack>
          </Box>
        </Group>
      </Box>

      {/* Edit Control Modal */}
      <EditControl
        opened={editModalOpened}
        control={
          selectedPlugin
            ? {
                id: 0,
                name: selectedPlugin.name,
                control: {
                  description: selectedPlugin.description,
                  enabled: true,
                  local: false,
                  applies_to: "llm_call" as const,
                  check_stage: "post" as const,
                  selector: {
                    path: "*",
                  },
                  evaluator: {
                    plugin: selectedPlugin.id,
                    config: getDefaultConfigForPlugin(selectedPlugin.id),
                  },
                  action: { decision: "deny" as const },
                },
              }
            : null
        }
        onClose={handleEditModalClose}
        onSave={handleEditModalSave}
      />
    </Modal>
  );
}
