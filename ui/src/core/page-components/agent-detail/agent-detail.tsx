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
import React, { useMemo, useRef, useState } from 'react';

import { ErrorBoundary } from '@/components/error-boundary';
import type { Control } from '@/core/api/types';
import { SearchInput } from '@/core/components/search-input';
import { getAgentRoute } from '@/core/constants/agent-routes';
import { MODAL_NAMES } from '@/core/constants/modal-routes';
import { useAgent } from '@/core/hooks/query-hooks/use-agent';
import { useAgentControls } from '@/core/hooks/query-hooks/use-agent-controls';
import { useHasMonitorData } from '@/core/hooks/query-hooks/use-has-monitor-data';
import { useUpdateControl } from '@/core/hooks/query-hooks/use-update-control';
import { useUpdateControlMetadata } from '@/core/hooks/query-hooks/use-update-control-metadata';
import { useModalRoute } from '@/core/hooks/use-modal-route';
import { useQueryParam } from '@/core/hooks/use-query-param';
import { useTimeRangePreference } from '@/core/hooks/use-time-range-preference';
import { useAuth } from '@/core/providers/auth-provider';

import { ControlsTab } from './controls/controls-tab';
import { useControlsTableColumns } from './controls/table-columns';
import { useDeleteControlFlow } from './controls/use-delete-control-flow';
import { ControlStoreModal } from './modals/control-store';
import { EditControlContent } from './modals/edit-control/edit-control-content';
import { AgentsMonitor, TIME_RANGE_SEGMENTS } from './monitor';

type AgentDetailPageProps = {
  agentId: string;
  defaultTab?: 'controls' | 'monitor';
  standaloneTab?: 'controls' | 'monitor';
};

const AgentDetailPage = ({
  agentId,
  defaultTab,
  standaloneTab,
}: AgentDetailPageProps) => {
  const router = useRouter();
  const { auth } = useAuth();
  const canManageControls =
    auth.status === 'not-required' ||
    (auth.status === 'authenticated' && auth.isAdmin);
  const { modal, controlId, openModal, closeModal } = useModalRoute();
  const [selectedControl, setSelectedControl] = useState<Control | null>(null);
  const [searchQuery] = useQueryParam('q');
  const [timeRangeValue, setTimeRangeValue] = useTimeRangePreference();

  const controlStoreOpened =
    canManageControls && modal === MODAL_NAMES.CONTROL_STORE;
  const editModalOpened = canManageControls && modal === MODAL_NAMES.EDIT;

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

  const needsInitialTabCheck = !defaultTab && !standaloneTab;
  const { data: hasMonitorData, isLoading: checkingMonitorData } =
    useHasMonitorData(agentId, {
      enabled: needsInitialTabCheck,
    });

  const updateControl = useUpdateControl();
  const updateControlMetadata = useUpdateControlMetadata();
  const editCloseRef = useRef<(() => void) | null>(null);

  const handleCloseEditModal = () => {
    // If EditControlContent has registered a close handler (with dirty check),
    // use it. Otherwise close directly.
    if (editCloseRef.current) {
      editCloseRef.current();
      return;
    }
    closeModal();
  };

  const { handleDeleteControl, removeControlFromAgent } = useDeleteControlFlow({
    agentId,
    selectedControl,
    onCloseEditModal: handleCloseEditModal,
  });

  const [activeTab, setActiveTab] = useState<string | null>(() => {
    if (standaloneTab) return standaloneTab;
    if (defaultTab === 'monitor') return 'monitor';
    if (defaultTab === 'controls') return 'controls';
    return 'controls';
  });

  const hasCheckedInitialTab = React.useRef(false);
  React.useEffect(() => {
    if (
      !defaultTab &&
      !standaloneTab &&
      !hasCheckedInitialTab.current &&
      !checkingMonitorData
    ) {
      hasCheckedInitialTab.current = true;
      if (hasMonitorData) {
        setActiveTab('monitor');
        router.replace(
          getAgentRoute(agentId, { tab: 'monitor', query: router.query }),
          undefined,
          {
            shallow: true,
          }
        );
      } else {
        setActiveTab('controls');
        router.replace(
          getAgentRoute(agentId, { tab: 'controls', query: router.query }),
          undefined,
          {
            shallow: true,
          }
        );
      }
    }
  }, [
    defaultTab,
    standaloneTab,
    checkingMonitorData,
    hasMonitorData,
    agentId,
    router,
  ]);

  const visibleTab = standaloneTab ?? activeTab;

  const controls = useMemo(() => {
    const allControls = controlsResponse?.controls || [];
    if (!searchQuery.trim()) return allControls;
    const query = searchQuery.toLowerCase();
    return allControls.filter((control) => {
      const description =
        'description' in control.control ? control.control.description : null;
      return (
        control.name.toLowerCase().includes(query) ||
        description?.toLowerCase().includes(query)
      );
    });
  }, [controlsResponse, searchQuery]);

  // Sync selectedControl to URL controlId when edit modal is open.
  // We do not clear selectedControl on close so modal content stays mounted
  // during the close animation (avoids content disappearing before title/backdrop).
  React.useEffect(() => {
    if (!editModalOpened || !controlId || !controlsResponse?.controls) return;
    const control = controlsResponse.controls.find(
      (c) => c.id.toString() === controlId
    );
    setSelectedControl(control ?? null);
  }, [editModalOpened, controlId, controlsResponse]);

  const handleEditControl = (control: Control) => {
    openModal(MODAL_NAMES.EDIT, { controlId: control.id.toString() });
  };

  const columns = useControlsTableColumns({
    agentId,
    canManageControls,
    updateControl,
    updateControlMetadata,
    removeControlFromAgent,
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

  const handleEditControlSuccess = () => {
    closeModal();
    // Do not clear selectedControl so modal content stays visible during close animation.
  };

  function renderEditModalBody() {
    if (selectedControl) {
      return (
        <EditControlContent
          control={selectedControl}
          agentId={agentId}
          onClose={handleCloseEditModal}
          onSuccess={handleEditControlSuccess}
          onCloseRef={editCloseRef}
        />
      );
    }
    // We have a controlId in the URL and the controls list has loaded, but no control in that list matched → invalid or deleted
    const controlNotFound = controlId && controlsResponse && !selectedControl;
    if (controlNotFound) {
      return (
        <Stack gap="md" py="md">
          <Alert
            icon={<IconAlertCircle size={16} />}
            title="Control not found"
            color="orange"
            variant="light"
          >
            <Text size="sm">
              No control matches ID &quot;{controlId}&quot;. It may have been
              deleted or the link is invalid.
            </Text>
          </Alert>
          <Group justify="flex-end">
            <Button
              variant="outline"
              size="sm"
              onClick={handleCloseEditModal}
              data-testid="edit-modal-close-invalid-control"
            >
              Close
            </Button>
          </Group>
        </Stack>
      );
    }

    if (controlId) {
      return (
        <Center py="xl">
          <Stack align="center" gap="md">
            <Loader size="sm" />
            <Text size="sm" c="dimmed">
              Loading control…
            </Text>
          </Stack>
        </Center>
      );
    }
    return null;
  }

  return (
    <Box p="xl" maw={1400} mx="auto" my={0}>
      <Stack gap="lg">
        <Stack gap={4}>
          <Title order={2} fw={600}>
            {standaloneTab === 'controls'
              ? 'Controls'
              : standaloneTab === 'monitor'
                ? 'Monitor'
                : agent.agent.agent_name}
          </Title>
          {standaloneTab ? (
            <Text size="sm" c="dimmed">
              {standaloneTab === 'controls'
                ? 'Rule buckets assigned to your Agent Control access.'
                : 'DefenseClaw enforcement history for your authorized scope.'}
            </Text>
          ) : agent.agent.agent_description ? (
            <Text size="sm" c="dimmed">
              {agent.agent.agent_description}
            </Text>
          ) : null}
        </Stack>

        <Tabs
          value={visibleTab}
          onChange={(value) => {
            if (standaloneTab) return;
            setActiveTab(value);
            if (value === 'monitor') {
              router.push(
                getAgentRoute(agentId, { tab: 'monitor', query: router.query }),
                undefined,
                {
                  shallow: true,
                }
              );
            } else if (value === 'controls') {
              router.push(
                getAgentRoute(agentId, {
                  tab: 'controls',
                  query: router.query,
                }),
                undefined,
                {
                  shallow: true,
                }
              );
            }
          }}
        >
          <Box mb="md">
            <Group justify="space-between" pos="relative">
              {standaloneTab ? (
                <Box />
              ) : (
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
              )}

              <Group
                gap="md"
                pos={standaloneTab ? 'static' : 'absolute'}
                right={standaloneTab ? undefined : 0}
                top={standaloneTab ? undefined : '-8px'}
              >
                {visibleTab === 'controls' ? (
                  <>
                    <SearchInput
                      queryKey="q"
                      placeholder="Search controls..."
                      w={250}
                      size="sm"
                      data-testid="controls-search-input"
                    />
                    {canManageControls ? (
                      <Button
                        variant="filled"
                        size="sm"
                        data-testid="add-control-button"
                        h={32}
                        onClick={() => openModal('control-store')}
                      >
                        Add Control
                      </Button>
                    ) : null}
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
              canManageControls={canManageControls}
              onAddControl={() => openModal(MODAL_NAMES.CONTROL_STORE)}
            />
          </Tabs.Panel>

          <Tabs.Panel value="monitor" pt="lg">
            <ErrorBoundary variant="page">
              {agent?.agent.agent_name && visibleTab === 'monitor' ? (
                <AgentsMonitor
                  agentUuid={agent.agent.agent_name}
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

      {/* Edit Control Modal */}
      <Modal
        opened={editModalOpened}
        onClose={handleCloseEditModal}
        title="Edit Control"
        size="xl"
        closeOnEscape={false}
        styles={{
          title: { fontSize: '18px', fontWeight: 600 },
          content: { maxWidth: '1500px', width: '95vw' },
        }}
      >
        <ErrorBoundary variant="modal">{renderEditModalBody()}</ErrorBoundary>
      </Modal>
    </Box>
  );
};

export default AgentDetailPage;
