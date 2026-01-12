import {
  Box,
  Group,
  Modal,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { Button, Table } from "@rungalileo/jupiter-ds";
import {
  IconSearch,
  IconSettings,
  IconSparkles,
  IconX,
} from "@tabler/icons-react";
import { type ColumnDef } from "@tanstack/react-table";
import { useState } from "react";

interface Control {
  id: string;
  name: string;
  controls: number;
  description: string;
  tag: string;
}

interface ControlStoreModalProps {
  opened: boolean;
  onClose: () => void;
}

const GALILEO_STANDARD_CONTROLS: Control[] = [
  {
    id: "sql",
    name: "SQL",
    controls: 1,
    description: "Validates SQL queries for syntax and security",
    tag: "security",
  },
  {
    id: "regex",
    name: "Regex",
    controls: 1,
    description: "Pattern matching and validation for text",
    tag: "validation",
  },
];

export function ControlStoreModal({ opened, onClose }: ControlStoreModalProps) {
  const [selectedSource, setSelectedSource] = useState<"galileo" | "custom">(
    "galileo"
  );
  const [searchQuery, setSearchQuery] = useState("");

  const columns: ColumnDef<Control>[] = [
    {
      id: "name",
      header: "Name",
      accessorKey: "name",
      size: 80,
      cell: ({ row }: { row: any }) => (
        <Group gap='xs'>
          <Text size='sm' fw={500}>
            {row.original.name}
          </Text>
        </Group>
      ),
    },
    {
      id: "controls",
      header: "Controls",
      accessorKey: "controls",
      size: 80,
      cell: ({ row }: { row: any }) => (
        <Text size='sm'>{row.original.controls}</Text>
      ),
    },
    {
      id: "description",
      header: "Description",
      accessorKey: "description",
      size: 200,
      cell: ({ row }: { row: any }) => (
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
      cell: () => (
        <Button variant='outline' size='sm' data-testid='add-control-button'>
          Add
        </Button>
      ),
    },
  ];

  const filteredControls =
    selectedSource === "galileo"
      ? GALILEO_STANDARD_CONTROLS.filter((control) =>
          control.name.toLowerCase().includes(searchQuery.toLowerCase())
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
        <Box
          p='md'
          style={{ borderBottom: "1px solid var(--mantine-color-gray-3)" }}
        >
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

        {/* Content */}
        <Group align='stretch' gap={0} style={{ minHeight: 500 }}>
          {/* Left Sidebar */}
          <Box
            w={175}
            p='md'
            style={{
              borderRight: "1px solid var(--mantine-color-gray-3)",
            }}
          >
            <Stack gap='lg'>
              <Stack gap='xs'>
                <Text size='xs' fw={600} c='dimmed' tt='uppercase'>
                  Source
                </Text>
                <Stack gap={4}>
                  <Group
                    gap='xs'
                    p='xs'
                    style={{
                      cursor: "pointer",
                      borderRadius: 6,
                      backgroundColor:
                        selectedSource === "galileo"
                          ? "var(--mantine-color-blue-0)"
                          : "transparent",
                    }}
                    onClick={() => setSelectedSource("galileo")}
                  >
                    <IconSparkles size={18} />
                    <Text
                      size='sm'
                      fw={selectedSource === "galileo" ? 600 : 400}
                    >
                      OOB standard
                    </Text>
                  </Group>
                  <Group
                    gap='xs'
                    p='xs'
                    style={{
                      cursor: "pointer",
                      borderRadius: 6,
                      backgroundColor:
                        selectedSource === "custom"
                          ? "var(--mantine-color-blue-0)"
                          : "transparent",
                    }}
                    onClick={() => setSelectedSource("custom")}
                  >
                    <IconSettings size={18} />
                    <Text
                      size='sm'
                      fw={selectedSource === "custom" ? 600 : 400}
                    >
                      Custom
                    </Text>
                  </Group>
                </Stack>
              </Stack>
            </Stack>
          </Box>

          {/* Right Content */}
          <Box style={{ flex: 1 }} p='md'>
            <Stack gap='md'>
              {/* Search and Docs Link */}
              <Group justify='space-between'>
                <TextInput
                  placeholder='Search or apply filter...'
                  leftSection={<IconSearch size={16} />}
                  style={{ flex: 1, maxWidth: "250px" }}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
                <Text size='sm' c='dimmed'>
                  Looking to add custom control?{" "}
                  <Text
                    component='a'
                    href='#'
                    c='blue'
                    size='sm'
                    style={{ textDecoration: "none" }}
                  >
                    Check our Docs ↗
                  </Text>
                </Text>
              </Group>

              {/* Table or Empty State */}
              {selectedSource === "galileo" ? (
                filteredControls.length > 0 ? (
                  <Table
                    columns={columns}
                    data={filteredControls}
                    highlightOnHover
                  />
                ) : (
                  <Box
                    p='xl'
                    style={{
                      textAlign: "center",
                      border: "1px solid var(--mantine-color-gray-3)",
                      borderRadius: 8,
                    }}
                  >
                    <Text c='dimmed'>No controls found</Text>
                  </Box>
                )
              ) : (
                <Box
                  p='xl'
                  style={{
                    textAlign: "center",
                    border: "1px solid var(--mantine-color-gray-3)",
                    borderRadius: 8,
                  }}
                >
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
                </Box>
              )}
            </Stack>
          </Box>
        </Group>
      </Box>
    </Modal>
  );
}
