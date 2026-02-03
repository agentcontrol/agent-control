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
import { IconAlertCircle, IconSearch, IconX } from "@tabler/icons-react";
import { type ColumnDef } from "@tanstack/react-table";
import { useMemo, useState } from "react";

import { ErrorBoundary } from "@/components/error-boundary";
import type { EvaluatorInfo } from "@/core/api/types";
import { useAgent } from "@/core/hooks/query-hooks/use-agent";
import { useEvaluators } from "@/core/hooks/query-hooks/use-evaluators";
import { useModalRoute } from "@/core/hooks/use-modal-route";

import { EditControlContent } from "../edit-control/edit-control-content";
import { sanitizeControlNamePart } from "../edit-control/utils";

type EvaluatorWithId = EvaluatorInfo & { id: string };

/**
 * Default evaluator configs for each evaluator type
 * Based on backend models in agent_control_models/controls.py
 */
const DEFAULT_EVALUATOR_CONFIGS: Record<string, Record<string, unknown>> = {
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

function getDefaultConfigForEvaluator(
  evaluatorId: string
): Record<string, unknown> {
  return DEFAULT_EVALUATOR_CONFIGS[evaluatorId] ?? {};
}

interface AddNewControlModalProps {
  opened: boolean;
  onClose: () => void;
  agentId: string;
}

export function AddNewControlModal({
  opened,
  onClose,
  agentId,
}: AddNewControlModalProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const { submodal, evaluator, openModal, closeSubmodal, closeModal } = useModalRoute();
  const { data: evaluatorsData, isLoading, error } = useEvaluators();
  const { data: agent } = useAgent(agentId);
  const agentName = agent?.agent?.agent_name ?? agentId;

  // Derive submodal open state from URL
  const editModalOpened = submodal === "create";

  // Find selected evaluator from URL or state
  const selectedEvaluator = useMemo(() => {
    if (evaluator && evaluatorsData) {
      const evaluatorData = evaluatorsData[evaluator];
      if (evaluatorData) {
        return { ...evaluatorData, id: evaluator };
      }
    }
    return null;
  }, [evaluator, evaluatorsData]);

  const handleAddClick = (evaluator: EvaluatorWithId) => {
    openModal("control-store", { submodal: "create", evaluator: evaluator.id });
  };

  const handleEditModalClose = () => {
    closeSubmodal();
  };

  const handleEditModalSuccess = () => {
    // Close all modals on successful create
    // Use closeModal to close the entire modal stack (control-store + add-new + create)
    closeModal();
  };

  // Transform evaluators record to array for table display
  const evaluators = useMemo(() => {
    if (!evaluatorsData) return [];
    return Object.entries(evaluatorsData).map(([key, evaluator]) => ({
      ...evaluator,
      id: key,
    }));
  }, [evaluatorsData]);

  const draftControl = useMemo(() => {
    if (!selectedEvaluator) return null;
    const name = `${sanitizeControlNamePart(selectedEvaluator.name)}-control-for-${sanitizeControlNamePart(agentName)}`;
    return {
      id: 0,
      name,
      control: {
        description: selectedEvaluator.description,
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
          name: selectedEvaluator.id,
          config: getDefaultConfigForEvaluator(selectedEvaluator.id),
        },
        action: { decision: "deny" as const },
      },
    };
  }, [selectedEvaluator, agentName]);

  const columns: ColumnDef<EvaluatorInfo & { id: string }>[] = [
    {
      id: "name",
      header: "Name",
      accessorKey: "name",
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
      id: "description",
      header: "Description",
      accessorKey: "description",
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
      id: "actions",
      header: "",
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

  const filteredEvaluators = evaluators.filter((evaluator) =>
    evaluator.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

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
          width: "800px",
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
            Select an evaluator to create a new control
          </Text>
        </Box>
        <Divider />

        {/* Content */}
        <Box p="md" style={{ height: "500px", display: "flex", flexDirection: "column" }}>
          <Stack gap="md" style={{ flex: 1, minHeight: 0 }}>
            {/* Search and Docs Link */}
            <Group justify="space-between">
              <TextInput
                placeholder="Search evaluators..."
                leftSection={<IconSearch size={16} />}
                flex={1}
                maw={250}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
                <Text size="sm" c="dimmed">
                  Learn here on how to add new type of evaluator.{" "}
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
                  <Text c="red">Failed to load evaluators</Text>
                </Stack>
              </Paper>
            ) : filteredEvaluators.length > 0 ? (
              <Box style={{ flex: 1, minHeight: 0 }}>
                <Table
                  columns={columns}
                  data={filteredEvaluators}
                  highlightOnHover
                  maxHeight="100%"
                />
              </Box>
            ) : (
              <Paper p="xl" withBorder radius="sm" ta="center">
                <Text c="dimmed">No evaluators found</Text>
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
        styles={{
          title: { fontSize: "18px", fontWeight: 600 },
          content: { maxWidth: "1500px", width: "90vw" },
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
    </Modal>
  );
}
