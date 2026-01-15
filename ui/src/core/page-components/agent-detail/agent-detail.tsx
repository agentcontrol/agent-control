import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Center,
  Group,
  Loader,
  Paper,
  Stack,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { Button, Switch, Table } from "@rungalileo/jupiter-ds";
import {
  IconAlertCircle,
  IconInbox,
  IconPencil,
  IconSearch,
} from "@tabler/icons-react";
import { type ColumnDef } from "@tanstack/react-table";
import { useState } from "react";

import type { Control } from "@/core/api/types";
import { useAgent } from "@/core/hooks/query-hooks/use-agent";
import { useAgentControls } from "@/core/hooks/query-hooks/use-agent-controls";
import { useUpdateControl } from "@/core/hooks/query-hooks/use-update-control";

import { ControlStoreModal } from "./control-store-modal";
import { EditControl } from "./edit-control";

interface AgentDetailPageProps {
  agentId: string;
}

const AgentDetailPage = ({ agentId }: AgentDetailPageProps) => {
  const [activeTab, setActiveTab] = useState<string | null>("controls");
  const [editModalOpened, setEditModalOpened] = useState(false);
  const [controlStoreOpened, setControlStoreOpened] = useState(false);
  const [selectedControl, setSelectedControl] = useState<Control | null>(null);

  // Fetch agent details and controls
  const {
    data: agent,
    isLoading: agentLoading,
    error: agentError,
  } = useAgent(agentId);
  const {
    data: controlsResponse,
    isLoading: controlsLoading,
    error: controlsError,
  } = useAgentControls(agentId);
  const updateControl = useUpdateControl();

  const controls = controlsResponse?.controls || [];

  // Loading state
  if (agentLoading) {
    return (
      <Box p='xl' maw={1400} mx='auto' my={0}>
        <Center h={400}>
          <Stack align='center' gap='md'>
            <Loader size='lg' />
            <Text c='dimmed'>Loading agent details...</Text>
          </Stack>
        </Center>
      </Box>
    );
  }

  // Error state
  if (agentError || !agent) {
    return (
      <Box p='xl' maw={1400} mx='auto' my={0}>
        <Alert
          icon={<IconAlertCircle size={16} />}
          title='Error loading agent'
          color='red'
        >
          Failed to fetch agent details. Please try again later.
        </Alert>
      </Box>
    );
  }

  // Define table columns
  const columns: ColumnDef<Control>[] = [
    {
      id: "enabled",
      header: "",
      size: 60,
      cell: ({ row }: { row: any }) => (
        <Switch
          checked={row.original.control?.enabled ?? false}
          color='violet'
          onChange={(e) => {
            const control = row.original as Control;
            updateControl.mutate({
              agentId,
              controlId: control.id,
              definition: {
                ...control.control,
                enabled: e.currentTarget.checked,
              },
            });
          }}
        />
      ),
    },
    {
      id: "name",
      header: "Control",
      accessorKey: "name",
      cell: ({ row }: { row: any }) => (
        <Text size='sm' fw={500}>
          {row.original.name}
        </Text>
      ),
    },
    {
      id: "applies_to",
      header: "Applies to",
      accessorKey: "control.applies_to",
      size: 120,
      cell: ({ row }: { row: any }) => (
        <Badge
          variant='light'
          color={
            row.original.control?.applies_to === "llm_call" ? "blue" : "green"
          }
          size='sm'
        >
          {row.original.control?.applies_to === "llm_call"
            ? "LLM Call"
            : "Tool Call"}
        </Badge>
      ),
    },
    {
      id: "check_stage",
      header: "Stage",
      accessorKey: "control.check_stage",
      size: 100,
      cell: ({ row }: { row: any }) => (
        <Badge
          variant='light'
          color={
            row.original.control?.check_stage === "pre" ? "violet" : "orange"
          }
          size='sm'
        >
          {row.original.control?.check_stage === "pre" ? "Pre" : "Post"}
        </Badge>
      ),
    },
    {
      id: "actions",
      header: "",
      size: 60,
      cell: ({ row }: { row: any }) => (
        <ActionIcon
          variant='subtle'
          color='gray'
          size='sm'
          onClick={() => handleEditControl(row.original)}
        >
          <IconPencil size={16} />
        </ActionIcon>
      ),
    },
  ];

  const handleEditControl = (control: Control) => {
    setSelectedControl(control);
    setEditModalOpened(true);
  };

  const handleCloseEditModal = () => {
    setEditModalOpened(false);
    setSelectedControl(null);
  };

  const handleSaveControl = (data: Control) => {
    updateControl.mutate(
      {
        agentId,
        controlId: data.id,
        definition: data.control,
      },
      {
        onSuccess: () => {
          setEditModalOpened(false);
          setSelectedControl(null);
        },
        onError: (err) => {
          console.error("Failed to update control:", err);
        },
      }
    );
  };

  return (
    <Box p='xl' maw={1400} mx='auto' my={0}>
      <Stack gap='lg'>
        {/* Header */}
        <Stack gap={4}>
          <Title order={2} fw={600}>
            {agent.agent.agent_name}
          </Title>
          {agent.agent.agent_description && (
            <Text size='sm' c='dimmed'>
              {agent.agent.agent_description}
            </Text>
          )}
        </Stack>

        {/* Tabs */}
        <Tabs value={activeTab} onChange={setActiveTab}>
          <Box mb='md'>
            <Group justify='space-between' pos='relative'>
              <Tabs.List>
                <Tabs.Tab
                  value='controls'
                  leftSection={<Text size='sm'>🎛️</Text>}
                >
                  Controls
                </Tabs.Tab>
                <Tabs.Tab
                  value='charts'
                  leftSection={<Text size='sm'>📊</Text>}
                >
                  Charts
                </Tabs.Tab>
                <Tabs.Tab
                  value='agent-graph'
                  leftSection={<Text size='sm'>🔗</Text>}
                >
                  Agent graph
                </Tabs.Tab>
                <Tabs.Tab value='logs' leftSection={<Text size='sm'>📋</Text>}>
                  Logs
                </Tabs.Tab>
              </Tabs.List>

              <Group gap='md' pos='absolute' right={0} top='-8px'>
                <TextInput
                  placeholder='Search or apply filter...'
                  leftSection={<IconSearch size={16} />}
                  w={300}
                  h={32}
                  size='xs'
                />
                <Button
                  variant='filled'
                  color='violet'
                  size='sm'
                  data-testid='add-control-button'
                  h={32}
                  onClick={() => setControlStoreOpened(true)}
                >
                  Add Control
                </Button>
              </Group>
            </Group>
          </Box>

          <Tabs.Panel value='controls' pt='lg'>
            {/* Loading state for controls */}
            {controlsLoading ? (
              <Center py='xl'>
                <Stack align='center' gap='md'>
                  <Loader size='md' />
                  <Text c='dimmed'>Loading controls...</Text>
                </Stack>
              </Center>
            ) : controlsError ? (
              <Alert
                icon={<IconAlertCircle size={16} />}
                title='Error loading controls'
                color='red'
              >
                Failed to fetch controls. Please try again later.
              </Alert>
            ) : controls.length === 0 ? (
              <Paper p='xl' withBorder radius='sm' ta='center'>
                <Stack align='center' gap='md' py='xl'>
                  <IconInbox size={48} color='var(--mantine-color-gray-4)' />
                  <Stack gap='xs' align='center'>
                    <Text fw={500} c='dimmed'>
                      No controls configured
                    </Text>
                    <Text size='sm' c='dimmed'>
                      This agent doesn&apos;t have any controls set up yet.
                    </Text>
                  </Stack>
                  <Button
                    variant='filled'
                    mt='md'
                    data-testid='add-control-button'
                    onClick={() => setControlStoreOpened(true)}
                  >
                    Add Control
                  </Button>
                </Stack>
              </Paper>
            ) : (
              <Table
                columns={columns}
                data={controls}
                highlightOnHover
                withColumnBorders
              />
            )}
          </Tabs.Panel>

          <Tabs.Panel value='charts' pt='lg'>
            <Text c='dimmed'>Charts view coming soon...</Text>
          </Tabs.Panel>

          <Tabs.Panel value='agent-graph' pt='lg'>
            <Text c='dimmed'>Agent graph view coming soon...</Text>
          </Tabs.Panel>

          <Tabs.Panel value='logs' pt='lg'>
            <Text c='dimmed'>Logs view coming soon...</Text>
          </Tabs.Panel>
        </Tabs>
      </Stack>

      {/* Control Store Modal */}
      <ControlStoreModal
        opened={controlStoreOpened}
        onClose={() => setControlStoreOpened(false)}
        agentId={agentId}
      />

      {/* Edit Control Modal */}
      <EditControl
        opened={editModalOpened}
        control={selectedControl}
        onClose={handleCloseEditModal}
        onSave={handleSaveControl}
      />
    </Box>
  );
};

export default AgentDetailPage;
