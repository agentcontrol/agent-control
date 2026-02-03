import {
  Box,
  Group,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";

import type { ControlDefinitionFormProps } from "./types";

export function StepNameInput({ form }: ControlDefinitionFormProps) {
  const isRegexMode = form.values.step_name_mode === "regex";

  const handleRegexToggle = (enabled: boolean) => {
    form.setFieldValue("step_name_mode", enabled ? "regex" : "names");
  };

  return (
    <Box>
      <Group gap="xs" mb={4} wrap="nowrap">
        <Group gap={4}>
          <Text size="sm" fw={500}>
            Step name
          </Text>
          <Tooltip
            label={
              <Stack gap={0}>
                <Text size="xs">
                  {isRegexMode
                    ? "Optional RE2 pattern to match step names."
                    : "Comma-separated step names to scope this control."}
                </Text>
                <Text size="xs">
                  {isRegexMode
                    ? "Toggle off to use comma-separated step names."
                    : "Toggle on to use a regex pattern instead."}
                </Text>
              </Stack>
            }
          >
            <IconInfoCircle size={14} color="gray" />
          </Tooltip>
        </Group>
        <Switch
          size="xs"
          label="Regex"
          checked={isRegexMode}
          onChange={(e) => handleRegexToggle(e.currentTarget.checked)}
        />
      </Group>
      {isRegexMode ? (
        <TextInput
          size="sm"
          placeholder="^db_.*"
          {...form.getInputProps("step_name_regex")}
        />
      ) : (
        <TextInput
          size="sm"
          placeholder="search_db, fetch_user"
          {...form.getInputProps("step_names")}
        />
      )}
    </Box>
  );
}
