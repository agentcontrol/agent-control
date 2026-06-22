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
} from '@mantine/core';
import { Button, Table } from '@rungalileo/jupiter-ds';
import { IconAlertCircle, IconSearch, IconX } from '@tabler/icons-react';
import { type ColumnDef } from '@tanstack/react-table';
import { useMemo, useState } from 'react';

import { ErrorBoundary } from '@/components/error-boundary';
import type { RuleInfo } from '@/core/api/types';
import { MODAL_NAMES, SUBMODAL_NAMES } from '@/core/constants/modal-routes';
import { useRules } from '@/core/hooks/query-hooks/use-rules';
import { useModalRoute } from '@/core/hooks/use-modal-route';

import { EditControlContent } from '../edit-control/edit-control-content';
import { sanitizeControlNamePart } from '../edit-control/utils';

type RuleWithId = RuleInfo & { id: string };

/**
 * Default rule configs for each rule type
 * Based on backend models in agent_control_models/controls.py
 */
const DEFAULT_RULE_CONFIGS: Record<string, Record<string, unknown>> = {
  regex: {
    pattern: '^.*$',
  },
  list: {
    values: [],
    logic: 'any',
    match_on: 'match',
    match_mode: 'exact',
    case_sensitive: false,
  },
  'galileo.luna': {
    scorer_label: '',
    scorer_id: '',
    scorer_version_id: '',
    threshold: 0.5,
    operator: 'gte',
    payload_field: 'input',
    timeout_ms: 10000,
    config: null,
  },
};

function getDefaultConfigForRule(ruleId: string): Record<string, unknown> {
  return DEFAULT_RULE_CONFIGS[ruleId] ?? {};
}

function buildJsonDraftControl() {
  return {
    id: 0,
    name: 'new-json-control',
    control: {
      description: '',
      enabled: true,
      execution: 'server' as const,
      scope: {
        step_types: ['llm'],
        stages: ['post'] as ('post' | 'pre')[],
      },
      condition: {
        selector: {
          path: '*',
        },
        rule: {
          name: 'regex',
          config: getDefaultConfigForRule('regex'),
        },
      },
      action: { decision: 'deny' as const },
      tags: [],
    },
  };
}

type AddNewControlModalProps = {
  opened: boolean;
  onClose: () => void;
  agentId: string;
};

export function AddNewControlModal({
  opened,
  onClose,
  agentId,
}: AddNewControlModalProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const { submodal, rule, openModal, closeSubmodal, closeModal } =
    useModalRoute();
  const { data: rulesData, isLoading, error } = useRules();

  // Derive submodal open state from URL
  const editModalOpened = submodal === SUBMODAL_NAMES.CREATE;

  // Find selected rule from URL or state
  const selectedRule = useMemo(() => {
    if (rule && rulesData) {
      const ruleData = rulesData[rule];
      if (ruleData) {
        return { ...ruleData, id: rule };
      }
    }
    return null;
  }, [rule, rulesData]);

  const handleAddClick = (rule: RuleWithId) => {
    openModal(MODAL_NAMES.CONTROL_STORE, {
      submodal: SUBMODAL_NAMES.CREATE,
      rule: rule.id,
    });
  };

  const handleFromJsonClick = () => {
    openModal(MODAL_NAMES.CONTROL_STORE, {
      submodal: SUBMODAL_NAMES.CREATE,
    });
  };

  const handleEditModalClose = () => {
    closeSubmodal();
  };

  const handleEditModalSuccess = () => {
    // Close all modals on successful create
    // Use closeModal to close the entire modal stack (control-store + add-new + create)
    closeModal();
  };

  // Transform rules record to array for table display
  const rules = useMemo(() => {
    if (!rulesData) return [];
    return Object.entries(rulesData).map(([key, rule]) => ({
      ...rule,
      id: key,
    }));
  }, [rulesData]);

  const draftControl = useMemo(() => {
    if (selectedRule) {
      const name = `new-${sanitizeControlNamePart(selectedRule.name)}-control`;
      return {
        id: 0,
        name,
        control: {
          description: selectedRule.description,
          enabled: true,
          execution: 'server' as const,
          scope: {
            step_types: ['llm'],
            stages: ['post'] as ('post' | 'pre')[],
          },
          condition: {
            selector: {
              path: '*',
            },
            rule: {
              name: selectedRule.id,
              config: getDefaultConfigForRule(selectedRule.id),
            },
          },
          action: { decision: 'deny' as const },
        },
      };
    }

    return buildJsonDraftControl();
  }, [selectedRule]);

  const columns: ColumnDef<RuleInfo & { id: string }>[] = [
    {
      id: 'name',
      header: 'Name',
      accessorKey: 'name',
      size: 150,
      cell: ({ row }) => (
        <Group gap="xs">
          <Text size="sm" fw={500}>
            {row.original.name}
          </Text>
        </Group>
      ),
    },
    {
      id: 'description',
      header: 'Description',
      accessorKey: 'description',
      size: 400,
      cell: ({ row }) => (
        <Tooltip label={row.original.description} withArrow>
          <Text size="sm" c="dimmed" lineClamp={1}>
            {row.original.description}
          </Text>
        </Tooltip>
      ),
    },
    {
      id: 'actions',
      header: '',
      size: 100,
      cell: ({ row }) => (
        <Box pr="md">
          <Group justify="flex-end">
            <Button
              variant="outline"
              size="sm"
              data-testid="add-control-button"
              onClick={() => handleAddClick(row.original)}
            >
              Use
            </Button>
          </Group>
        </Box>
      ),
    },
  ];

  const filteredRules = rules.filter((rule) =>
    rule.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="xxl"
      padding={0}
      withCloseButton={false}
      closeOnEscape={false}
      styles={{
        body: {
          padding: 0,
          width: '800px',
        },
      }}
    >
      <Box>
        {/* Header */}
        <Box p="md">
          <Group justify="space-between" mb="xs">
            <Title order={3} fw={600}>
              Create Control
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
            Select a rule to create a new control or start from JSON
          </Text>
        </Box>
        <Divider />

        {/* Content */}
        <Box
          p="md"
          style={{ height: '500px', display: 'flex', flexDirection: 'column' }}
        >
          <Stack gap="md" style={{ flex: 1, minHeight: 0 }}>
            {/* Search and Docs Link */}
            <Group justify="space-between">
              <TextInput
                placeholder="Search rules..."
                leftSection={<IconSearch size={16} />}
                flex={1}
                maw={250}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              <Group gap="md" wrap="nowrap">
                <Button
                  variant="outline"
                  size="sm"
                  data-testid="from-json-button"
                  onClick={handleFromJsonClick}
                >
                  Write your own
                </Button>
                <Text size="sm" c="dimmed">
                  Learn here on how to add new type of rule.{' '}
                  <Text
                    component="a"
                    href="https://github.com/agentcontrol/agent-control/blob/main/README.md"
                    c="blue"
                    size="sm"
                    td="none"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Docs ↗
                  </Text>
                </Text>
              </Group>
            </Group>

            {/* Table or Empty State */}
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
                  <Text c="red">Failed to load rules</Text>
                </Stack>
              </Paper>
            ) : filteredRules.length > 0 ? (
              <Box style={{ flex: 1, minHeight: 0 }}>
                <Table
                  columns={columns}
                  data={filteredRules}
                  highlightOnHover
                  maxHeight="100%"
                />
              </Box>
            ) : (
              <Paper p="xl" withBorder radius="sm" ta="center">
                <Text c="dimmed">No rules found</Text>
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
        size="xl"
        keepMounted={false}
        closeOnEscape={false}
        styles={{
          title: { fontSize: '18px', fontWeight: 600 },
          content: { maxWidth: '1500px', width: '90vw' },
        }}
      >
        <ErrorBoundary variant="modal">
          {draftControl ? (
            <EditControlContent
              control={draftControl}
              agentId={agentId}
              mode="create"
              initialEditorMode={selectedRule ? 'form' : 'json'}
              onClose={handleEditModalClose}
              onSuccess={handleEditModalSuccess}
            />
          ) : null}
        </ErrorBoundary>
      </Modal>
    </Modal>
  );
}
