import {
  Alert,
  Box,
  Center,
  Group,
  Loader,
  Modal,
  Stack,
  Tabs,
  Text,
  Title,
} from '@mantine/core';
import { Button, TimeRangeSwitch } from '@rungalileo/jupiter-ds';
import { IconAlertCircle, IconChartBar, IconShield } from '@tabler/icons-react';
import { useRouter } from 'next/router';
import React, { useMemo, useState } from 'react';

import { ErrorBoundary } from '@/components/error-boundary';
import type { Control } from '@/core/api/types';
import { SearchInput } from '@/core/components/search-input';
import { MODAL_NAMES } from '@/core/constants/modal-routes';
import { useAgent } from '@/core/hooks/query-hooks/use-agent';
import { useAgentControls } from '@/core/hooks/query-hooks/use-agent-controls';
import { useHasMonitorData } from '@/core/hooks/query-hooks/use-has-monitor-data';
import { useUpdateControl } from '@/core/hooks/query-hooks/use-update-control';
import { useModalRoute } from '@/core/hooks/use-modal-route';
import { useQueryParam } from '@/core/hooks/use-query-param';
import { useTimeRangePreference } from '@/core/hooks/use-time-range-preference';

import { ControlsTab } from './controls/controls-tab';
import { useControlsTableColumns } from './controls/table-columns';
import { useDeleteControlFlow } from './controls/use-delete-control-flow';
import { ControlStoreModal } from './modals/control-store';
import { EditControlContent } from './modals/edit-control/edit-control-content';
import { AgentsMonitor, TIME_RANGE_SEGMENTS } from './monitor';

type AgentDetailPageProps = {
  agentId: string;
  defaultTab?: 'controls' | 'monitor';
};

const AgentDetailPage = ({ agentId, defaultTab }: AgentDetailPageProps) => {
  const router = useRouter();
  const { modal, controlId, openModal, closeModal } = useModalRoute();
  const [selectedControl, setSelectedControl] = useState<Control | null>(null);
  const [searchQuery] = useQueryParam('q');
  const [timeRangeValue, setTimeRangeValue] = useTimeRangePreference();

  const controlStoreOpened = modal === MODAL_NAMES.CONTROL_STORE;
  const editModalOpened = modal === MODAL_NAMES.EDIT;

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

  const needsInitialTabCheck = !defaultTab;
  const { data: hasMonitorData, isLoading: checkingMonitorData } =
    useHasMonitorData(agentId, {
      enabled: needsInitialTabCheck,
    });

  const updateControl = useUpdateControl();

  const handleCloseEditModal = () => {
    closeModal();
    setSelectedControl(null);
  };

  const { handleDeleteControl, deleteControl } = useDeleteControlFlow({
    agentId,
    selectedControl,
    onCloseEditModal: handleCloseEditModal,
  });

  const [activeTab, setActiveTab] = useState<string | null>(() => {
    if (defaultTab === 'monitor') return 'monitor';
    if (defaultTab === 'controls') return 'controls';
    return 'controls';
  });

  const hasCheckedInitialTab = React.useRef(false);
  React.useEffect(() => {
    if (!defaultTab && !hasCheckedInitialTab.current && !checkingMonitorData) {
      hasCheckedInitialTab.current = true;
      if (hasMonitorData) {
        setActiveTab('monitor');
        router.replace(`/agents/${agentId}/monitor`, undefined, {
          shallow: true,
        });
      } else {
        setActiveTab('controls');
        router.replace(`/agents/${agentId}/controls`, undefined, {
          shallow: true,
        });
      }
    }
  }, [defaultTab, checkingMonitorData, hasMonitorData, agentId, router]);

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

  React.useEffect(() => {
    if (
      editModalOpened &&
      controlId &&
      controlsResponse?.controls &&
      !selectedControl
    ) {
      const control = controlsResponse.controls.find(
        (c) => c.id.toString() === controlId
      );
      if (control) {
        setSelectedControl(control);
      }
    }
  }, [editModalOpened, controlId, controlsResponse, selectedControl]);

  const handleEditControl = (control: Control) => {
    openModal(MODAL_NAMES.EDIT, { controlId: control.id.toString() });
  };

  const columns = useControlsTableColumns({
    agentId,
    updateControl,
    deleteControl,
    onEditControl: handleEditControl,
    onDeleteControl: handleDeleteControl,
  });

  if (agentLoading) {
    return (
      <Box p="xl" maw={1400} mx="auto" my={0}>
        <Center h={400}>
          <Stack align="center" gap="md">
            <Loader size="lg" />
            <Text c="dimmed">Loading agent details...</Text>
          </Stack>
        </Center>
      </Box>
    );
  }

  if (agentError || !agent) {
    return (
      <Box p="xl" maw={1400} mx="auto" my={0}>
        <Alert
          icon={<IconAlertCircle size={16} />}
          title="Error loading agent"
          color="red"
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

  return (
    <Box p="xl" maw={1400} mx="auto" my={0}>
      <Stack gap="lg">
        <Stack gap={4}>
          <Title order={2} fw={600}>
            {agent.agent.agent_name}
          </Title>
          {agent.agent.agent_description ? (
            <Text size="sm" c="dimmed">
              {agent.agent.agent_description}
            </Text>
          ) : null}
        </Stack>

        <Tabs
          value={activeTab}
          onChange={(value) => {
            setActiveTab(value);
            if (value === 'monitor') {
              router.push(`/agents/${agentId}/monitor`, undefined, {
                shallow: true,
              });
            } else if (value === 'controls') {
              router.push(`/agents/${agentId}/controls`, undefined, {
                shallow: true,
              });
            }
          }}
        >
          <Box mb="md">
            <Group justify="space-between" pos="relative">
              <Tabs.List>
                <Tabs.Tab
                  value="controls"
                  leftSection={<IconShield size={16} />}
                >
                  Controls
                </Tabs.Tab>
                <Tabs.Tab
                  value="monitor"
                  leftSection={<IconChartBar size={16} />}
                >
                  Monitor
                </Tabs.Tab>
              </Tabs.List>

              <Group gap="md" pos="absolute" right={0} top="-8px">
                {activeTab === 'controls' ? (
                  <>
                    <SearchInput
                      queryKey="q"
                      placeholder="Search controls..."
                      w={250}
                      size="sm"
                    />
                    <Button
                      variant="filled"
                      size="sm"
                      data-testid="add-control-button"
                      h={32}
                      onClick={() => openModal('control-store')}
                    >
                      Add Control
                    </Button>
                  </>
                ) : (
                  <TimeRangeSwitch
                    value={timeRangeValue}
                    onChange={setTimeRangeValue}
                    allowCustomSelection={false}
                    segmentOptions={TIME_RANGE_SEGMENTS}
                  />
                )}
              </Group>
            </Group>
          </Box>

          <Tabs.Panel value="controls" pt="lg">
            <ControlsTab
              controls={controls}
              controlsLoading={controlsLoading}
              controlsError={controlsError}
              columns={columns}
              onAddControl={() => openModal(MODAL_NAMES.CONTROL_STORE)}
            />
          </Tabs.Panel>

          <Tabs.Panel value="monitor" pt="lg">
            <ErrorBoundary variant="page">
              {agent?.agent.agent_id && activeTab === 'monitor' ? (
                <AgentsMonitor
                  agentUuid={agent.agent.agent_id}
                  timeRangeValue={timeRangeValue}
                />
              ) : null}
            </ErrorBoundary>
          </Tabs.Panel>
        </Tabs>
      </Stack>

      <ControlStoreModal
        opened={controlStoreOpened}
        onClose={closeModal}
        agentId={agentId}
      />

      <Modal
        opened={editModalOpened}
        onClose={handleCloseEditModal}
        title="Edit Control"
        size="xl"
        styles={{
          title: { fontSize: '18px', fontWeight: 600 },
          content: { maxWidth: '1500px', width: '95vw' },
        }}
      >
        <ErrorBoundary variant="modal">
          {selectedControl ? (
            <EditControlContent
              control={selectedControl}
              agentId={agentId}
              onClose={handleCloseEditModal}
              onSuccess={handleCloseEditModal}
            />
          ) : null}
        </ErrorBoundary>
      </Modal>
    </Box>
  );
};

export default AgentDetailPage;
