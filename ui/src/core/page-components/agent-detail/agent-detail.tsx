import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Center,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Tabs,
  Text,
  Title,
} from "@mantine/core";
import { modals } from "@mantine/modals";
import { Button, Switch, Table } from "@rungalileo/jupiter-ds";
import {
  IconAlertCircle,
  IconChartBar,
  IconInbox,
  IconPencil,
  IconShield,
} from "@tabler/icons-react";
import { type ColumnDef } from "@tanstack/react-table";
import { useRouter } from "next/router";
import React, { useMemo, useState } from "react";

import { ErrorBoundary } from "@/components/error-boundary";
import type { Control } from "@/core/api/types";
import { SearchInput } from "@/core/components/search-input";
import { useAgent } from "@/core/hooks/query-hooks/use-agent";
import { useAgentControls } from "@/core/hooks/query-hooks/use-agent-controls";
import { useHasMonitorData } from "@/core/hooks/query-hooks/use-has-monitor-data";
import { useUpdateControl } from "@/core/hooks/query-hooks/use-update-control";
import { useModalRoute } from "@/core/hooks/use-modal-route";
import { useQueryParam } from "@/core/hooks/use-query-param";

import { ControlStoreModal } from "./modals/control-store";
import { EditControlContent } from "./modals/edit-control/edit-control-content";
import { AgentsMonitor } from "./monitor";

interface AgentDetailPageProps {
  agentId: string;
  defaultTab?: "controls" | "monitor";
}

const getStepTypeLabelAndColor = (
  stepType: string
): { label: string; color: string } => {
  switch (stepType) {
    case "llm":
      return { label: "LLM", color: "blue" };
    case "tool":
      return { label: "Tool", color: "green" };
    default:
      return { label: stepType, color: "gray" };
  }
};

const AgentDetailPage = ({ agentId, defaultTab }: AgentDetailPageProps) => {
  const router = useRouter();
  const { modal, controlId, openModal, closeModal } = useModalRoute();
  const [selectedControl, setSelectedControl] = useState<Control | null>(null);
  // Get search value for filtering (SearchInput handles the UI and URL sync)
  const [searchQuery] = useQueryParam("q");

  // Derive modal open state from URL
  const controlStoreOpened = modal === "control-store";
  const editModalOpened = modal === "edit";

  // Fetch agent details, controls, and stats in parallel
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
  
  // Lightweight check to determine initial tab (when no defaultTab specified)
  // Only checks if stats exist, doesn't fetch full data
  const needsInitialTabCheck = !defaultTab;
  const {
    data: hasMonitorData,
    isLoading: checkingMonitorData,
  } = useHasMonitorData(agentId, {
    enabled: needsInitialTabCheck,
  });
  
  const updateControl = useUpdateControl();

  // Determine initial tab based on:
  // 1. defaultTab prop (from route)
  // 2. stats data (if no defaultTab and stats exist, show monitor)
  // 3. Otherwise, show controls
  const [activeTab, setActiveTab] = useState<string | null>(() => {
    if (defaultTab === "monitor") return "monitor";
    if (defaultTab === "controls") return "controls";
    return "controls"; // Default fallback
  });

  // Set initial tab based on monitor data check (only if no defaultTab specified)
  const hasCheckedInitialTab = React.useRef(false);
  React.useEffect(() => {
    // Only check if no defaultTab is specified (i.e., accessing /agents/[id] directly)
    if (!defaultTab && !hasCheckedInitialTab.current && !checkingMonitorData) {
      hasCheckedInitialTab.current = true;
      
      if (hasMonitorData) {
        setActiveTab("monitor");
        router.replace(`/agents/${agentId}/monitor`, undefined, { shallow: true });
      } else {
        setActiveTab("controls");
        router.replace(`/agents/${agentId}/controls`, undefined, { shallow: true });
      }
    }
  }, [defaultTab, checkingMonitorData, hasMonitorData, agentId, router]);

  // Filter controls based on search query
  const controls = useMemo(() => {
    const allControls = controlsResponse?.controls || [];
    if (!searchQuery.trim()) return allControls;
    const query = searchQuery.toLowerCase();
    return allControls.filter(
      (control) =>
        control.name.toLowerCase().includes(query) ||
        control.control?.description?.toLowerCase().includes(query)
    );
  }, [controlsResponse, searchQuery]);

  // Load control when controlId is in URL
  React.useEffect(() => {
    if (editModalOpened && controlId && controlsResponse?.controls) {
      const control = controlsResponse.controls.find((c) => c.id.toString() === controlId);
      if (control) {
        setSelectedControl(control);
      }
    }
  }, [editModalOpened, controlId, controlsResponse]);

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
          <Stack gap="xs">
            <Text>Failed to fetch agent details. Please try again later.</Text>
            <Text size="sm" c="dimmed" mt="xs">
              Possible reasons:
            </Text>
            <Stack gap={4} pl="md">
              <Text size="sm" c="dimmed">
                • Check server for API errors
              </Text>
              <Text size="sm" c="dimmed">
                • The agent ID might be incorrect
              </Text>
            </Stack>
          </Stack>
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
      cell: ({ row }: { row: any }) => {
        const control = row.original as Control;
        const enabled = control.control?.enabled ?? false;
        return (
          <Switch
            checked={enabled}
            color="green.5"
            onChange={(e) => {
              const newEnabled = e.currentTarget.checked;
              modals.openConfirmModal({
                title: newEnabled ? "Enable control?" : "Disable control?",
                children: (
                  <Text size="sm" c="dimmed">
                    {newEnabled
                      ? `Enable "${control.name}"?`
                      : `Disable "${control.name}"?`}
                  </Text>
                ),
                labels: { confirm: "Confirm", cancel: "Cancel" },
                confirmProps: {
                  variant: "filled",
                  color: "violet",
                  size: "sm",
                  className: "confirm-modal-confirm-btn",
                },
                cancelProps: { variant: "default", size: "sm" },
                onConfirm: () =>
                  updateControl.mutate({
                    agentId,
                    controlId: control.id,
                    definition: {
                      ...control.control,
                      enabled: newEnabled,
                    },
                  }),
              });
            }}
          />
        );
      },
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
      id: "step_types",
      header: "Step types",
      accessorKey: "control.scope.step_types",
      size: 180,
      cell: ({ row }: { row: any }) => {
        const stepTypes = row.original.control?.scope?.step_types ?? [];
        if (stepTypes.length === 0) {
          return (
            <Badge variant='light' color='gray' size='sm'>
              All
            </Badge>
          );
        }

        return (
          <Group gap={4} wrap='nowrap'>
            {stepTypes.map((stepType: string) => {
              const { label, color } = getStepTypeLabelAndColor(stepType);
              return (
                <Badge key={stepType} variant='light' color={color} size='sm'>
                  {label}
                </Badge>
              );
            })}
          </Group>
        );
      },
    },
    {
      id: "stages",
      header: "Stages",
      accessorKey: "control.scope.stages",
      size: 120,
      cell: ({ row }: { row: any }) => {
        const stages = row.original.control?.scope?.stages ?? [];
        if (stages.length === 0) {
          return (
            <Badge variant='light' color='gray' size='sm'>
              All
            </Badge>
          );
        }

        if (stages.length > 1) {
          return (
            <Badge variant='light' color='gray' size='sm'>
              Pre/Post
            </Badge>
          );
        }

        const stage = stages[0];
        const label = stage === "pre" ? "Pre" : "Post";
        const color = stage === "pre" ? "violet" : "orange";
        return (
          <Badge variant='light' color={color} size='sm'>
            {label}
          </Badge>
        );
      },
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
    openModal("edit", { controlId: control.id.toString() });
  };

  const handleCloseEditModal = () => {
    closeModal();
    setSelectedControl(null);
  };

  const handleEditControlSuccess = () => {
    closeModal();
    setSelectedControl(null);
  };

  return (
    <Box 
      p='xl' 
      maw={1400} 
      mx='auto' 
      my={0}
    >
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
        <Tabs
          value={activeTab}
          onChange={(value) => {
            setActiveTab(value);
            // Update URL when tab changes
            if (value === "monitor") {
              router.push(`/agents/${agentId}/monitor`, undefined, { shallow: true });
            } else if (value === "controls") {
              router.push(`/agents/${agentId}/controls`, undefined, { shallow: true });
            }
          }}
        >
          <Box mb='md'>
            <Group justify='space-between' pos='relative'>
              <Tabs.List>
                <Tabs.Tab
                  value='controls'
                  leftSection={<IconShield size={16} />}
                >
                  Controls
                </Tabs.Tab>
                <Tabs.Tab
                  value='monitor'
                  leftSection={<IconChartBar size={16} />}
                >
                  Monitor
                </Tabs.Tab>
              </Tabs.List>

              {activeTab === "controls" && (
                <Group gap='md' pos='absolute' right={0} top='-8px'>
                  <SearchInput
                    queryKey="q"
                    placeholder="Search controls..."
                    w={250}
                    h={32}
                    size="xs"
                  />
                  <Button
                    variant='filled'
                    // color='violet'
                    size='sm'
                    data-testid='add-control-button'
                    h={32}
                    onClick={() => openModal("control-store")}
                  >
                    Add Control
                  </Button>
                </Group>
              )}
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
                    onClick={() => openModal("control-store")}
                  >
                    Add Control
                  </Button>
                </Stack>
              </Paper>
            ) : (
              <Box>
                <Table
                  columns={columns}
                  data={controls}
                  maxHeight='calc(100dvh - 270px)'
                  highlightOnHover
                  withColumnBorders
                      // scrollContainerProps={{
                      //   style: {
                      //     maxHeight: "calc(100dvh - 200px)",
                      //   },
                      // }}
                />
              </Box>
            )}
          </Tabs.Panel>

          <Tabs.Panel value='monitor' pt='lg'>
            <ErrorBoundary variant="page">
              {/* Only render AgentsMonitor when monitor tab is active to prevent polling on controls page */}
              {agent?.agent.agent_id && activeTab === "monitor" && (
                <AgentsMonitor agentUuid={agent.agent.agent_id} />
              )}
            </ErrorBoundary>
          </Tabs.Panel>
        </Tabs>
      </Stack>

      {/* Control Store Modal */}
      <ControlStoreModal
        opened={controlStoreOpened}
        onClose={closeModal}
        agentId={agentId}
      />

      {/* Edit Control Modal - Modal shell owned by parent, content wrapped in ErrorBoundary */}
      <Modal
        opened={editModalOpened}
        onClose={handleCloseEditModal}
        title="Edit Control"
        size="xl"
        styles={{
          title: { fontSize: "18px", fontWeight: 600 },
          content: { maxWidth: "1500px", width: "95vw" },
        }}
      >
        <ErrorBoundary variant="modal">
          {selectedControl && (
            <EditControlContent
              control={selectedControl}
              agentId={agentId}
              onClose={handleCloseEditModal}
              onSuccess={handleEditControlSuccess}
            />
          )}
        </ErrorBoundary>
      </Modal>
    </Box>
  );
};

export default AgentDetailPage;
