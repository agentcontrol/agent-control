import {
  Box,
  Group,
  MultiSelect,
  Select,
  Stack,
  Switch,
  TagsInput,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";

import type {
  ControlActionDecision,
  ControlExecution,
  ControlStage,
} from "@/core/api/types";

import type { ControlDefinitionFormProps } from "./types";

export const ControlDefinitionForm = ({ form }: ControlDefinitionFormProps) => {
  return (
    <Stack gap='md'>
      <Box>
        <Group gap={4} mb={4}>
          <Text size='sm' fw={500}>
            Enabled
          </Text>
          <Tooltip label='Whether this control is active'>
            <IconInfoCircle size={14} color='gray' />
          </Tooltip>
        </Group>
        <Switch
          size='sm'
          {...form.getInputProps("enabled", { type: "checkbox" })}
        />
      </Box>

      <Box>
        <Group gap={4} mb={4}>
          <Text size='sm' fw={500}>
            Step types
          </Text>
          <Tooltip label='Leave empty to apply to all step types'>
            <IconInfoCircle size={14} color='gray' />
          </Tooltip>
        </Group>
        <TagsInput
          data={["llm", "tool"]}
          size='sm'
          placeholder='All step types'
          clearable
          value={form.values.step_types}
          onChange={(value) => form.setFieldValue("step_types", value)}
        />
      </Box>

      <Box>
        <Group gap={4} mb={4}>
          <Text size='sm' fw={500}>
            Stages
          </Text>
          <Tooltip label='Leave empty to apply to both stages'>
            <IconInfoCircle size={14} color='gray' />
          </Tooltip>
        </Group>
        <MultiSelect
          data={[
            { value: "pre", label: "Pre (before execution)" },
            { value: "post", label: "Post (after execution)" },
          ]}
          size='sm'
          placeholder='All stages'
          clearable
          value={form.values.stages}
          onChange={(value) =>
            form.setFieldValue("stages", value as ControlStage[])
          }
        />
      </Box>

      <Box>
        <Group gap={4} mb={4}>
          <Text size='sm' fw={500}>
            Step names
          </Text>
          <Tooltip label='Comma-separated step names to scope this control'>
            <IconInfoCircle size={14} color='gray' />
          </Tooltip>
        </Group>
        <TextInput
          size='sm'
          placeholder='search_db, fetch_user'
          {...form.getInputProps("step_names")}
        />
      </Box>

      <Box>
        <Group gap={4} mb={4}>
          <Text size='sm' fw={500}>
            Step name regex
          </Text>
          <Tooltip label='Optional RE2 pattern to match step names'>
            <IconInfoCircle size={14} color='gray' />
          </Tooltip>
        </Group>
        <TextInput
          size='sm'
          placeholder='^db_.*'
          {...form.getInputProps("step_name_regex")}
        />
      </Box>

      <Box>
        <Group gap={4} mb={4}>
          <Text size='sm' fw={500}>
            Selector path
          </Text>
          <Tooltip label="Path to data using dot notation (e.g., 'input', 'output', 'context.user_id', 'name', '*')">
            <IconInfoCircle size={14} color='gray' />
          </Tooltip>
        </Group>
        <Select
          data={[
            { value: "*", label: "* (entire payload)" },
            { value: "input", label: "input" },
            { value: "output", label: "output" },
            { value: "context", label: "context" },
            { value: "name", label: "name" },
            { value: "type", label: "type" },
          ]}
          size='sm'
          searchable
          allowDeselect={false}
          {...form.getInputProps("selector_path")}
          onChange={(value) =>
            form.setFieldValue("selector_path", value || "*")
          }
        />
      </Box>

      <Box>
        <Group gap={4} mb={4}>
          <Text size='sm' fw={500}>
            Action
          </Text>
          <Tooltip label='What action to take when the control matches'>
            <IconInfoCircle size={14} color='gray' />
          </Tooltip>
        </Group>
        <Select
          data={[
            { value: "allow", label: "Allow" },
            { value: "deny", label: "Deny" },
            { value: "warn", label: "Warn" },
            { value: "log", label: "Log" },
          ]}
          size='sm'
          {...form.getInputProps("action_decision")}
          onChange={(value) =>
            form.setFieldValue(
              "action_decision",
              (value as ControlActionDecision) || "deny"
            )
          }
        />
      </Box>

      <Box>
        <Group gap={4} mb={4}>
          <Text size='sm' fw={500}>
            Execution environment
          </Text>
          <Tooltip label='Where this control runs: locally in SDK or on the server'>
            <IconInfoCircle size={14} color='gray' />
          </Tooltip>
        </Group>
        <Select
          data={[
            { value: "server", label: "Server" },
            { value: "sdk", label: "SDK" },
          ]}
          size='sm'
          {...form.getInputProps("execution")}
          onChange={(value) =>
            form.setFieldValue(
              "execution",
              (value as ControlExecution) || "server"
            )
          }
        />
      </Box>
    </Stack>
  );
};
