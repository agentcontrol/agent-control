import { Box, Group, Select, Stack, Switch, Text, Tooltip } from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";

import type {
  ControlActionDecision,
  ControlAppliesTo,
  ControlCheckStage,
} from "@/core/api/types";

import type { ControlDefinitionFormProps } from "./types";

export const ControlDefinitionForm = ({
  form,
}: ControlDefinitionFormProps) => {
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
            Applies to
          </Text>
          <Tooltip label='Which type of interaction this control applies to'>
            <IconInfoCircle size={14} color='gray' />
          </Tooltip>
        </Group>
        <Select
          data={[
            { value: "llm_call", label: "LLM Call" },
            { value: "tool_call", label: "Tool Call" },
          ]}
          size='sm'
          {...form.getInputProps("appliesTo")}
          onChange={(value) =>
            form.setFieldValue("appliesTo", (value as ControlAppliesTo) || "llm_call")
          }
        />
      </Box>

      <Box>
        <Group gap={4} mb={4}>
          <Text size='sm' fw={500}>
            Check stage
          </Text>
          <Tooltip label='When to execute this control (before or after the call)'>
            <IconInfoCircle size={14} color='gray' />
          </Tooltip>
        </Group>
        <Select
          data={[
            { value: "pre", label: "Pre (before execution)" },
            { value: "post", label: "Post (after execution)" },
          ]}
          size='sm'
          {...form.getInputProps("checkStage")}
          onChange={(value) =>
            form.setFieldValue("checkStage", (value as ControlCheckStage) || "post")
          }
        />
      </Box>

      <Box>
        <Group gap={4} mb={4}>
          <Text size='sm' fw={500}>
            Selector path
          </Text>
          <Tooltip label="Path to data using dot notation (e.g., 'input', 'output', 'arguments.query', '*' for all)">
            <IconInfoCircle size={14} color='gray' />
          </Tooltip>
        </Group>
        <Select
          data={[
            { value: "*", label: "* (entire payload)" },
            { value: "input", label: "input" },
            { value: "output", label: "output" },
            { value: "arguments", label: "arguments" },
            { value: "context", label: "context" },
            { value: "tool_name", label: "tool_name" },
          ]}
          size='sm'
          searchable
          allowDeselect={false}
          {...form.getInputProps("selectorPath")}
          onChange={(value) => form.setFieldValue("selectorPath", value || "*")}
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
          {...form.getInputProps("actionDecision")}
          onChange={(value) =>
            form.setFieldValue("actionDecision", (value as ControlActionDecision) || "deny")
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
            { value: "local", label: "Local (SDK)" },
          ]}
          size='sm'
          value={form.values.local ? "local" : "server"}
          onChange={(value) => form.setFieldValue("local", value === "local")}
        />
      </Box>
    </Stack>
  );
};
