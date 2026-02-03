import { Box, Checkbox, Select, Stack, Text, Textarea } from "@mantine/core";

import type { EvaluatorFormProps } from "../types";
import type { ListFormValues } from "./types";

export const ListForm = ({ form }: EvaluatorFormProps<ListFormValues>) => {
  return (
    <Stack gap='md'>
      <Box>
        <Text size='sm' fw={500} mb={4}>
          Values
        </Text>
        <Textarea
          placeholder='Enter values (one per line)'
          minRows={4}
          maxRows={8}
          autosize
          {...form.getInputProps("values")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          List of values to match against (one per line)
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Logic
        </Text>
        <Select
          data={[
            { value: "any", label: "Any (match if any value matches)" },
            { value: "all", label: "All (match if all values match)" },
          ]}
          size='sm'
          {...form.getInputProps("logic")}
          onChange={(value) =>
            form.setFieldValue(
              "logic",
              (value as ListFormValues["logic"]) || "any"
            )
          }
        />
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Match on
        </Text>
        <Select
          data={[
            { value: "match", label: "Match (trigger when matched)" },
            { value: "no_match", label: "No match (trigger when not matched)" },
          ]}
          size='sm'
          {...form.getInputProps("match_on")}
          onChange={(value) =>
            form.setFieldValue(
              "match_on",
              (value as ListFormValues["match_on"]) || "match"
            )
          }
        />
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Match mode
        </Text>
        <Select
          data={[
            { value: "exact", label: "Exact (full string match)" },
            { value: "contains", label: "Contains (substring match)" },
          ]}
          size='sm'
          {...form.getInputProps("match_mode")}
          onChange={(value) =>
            form.setFieldValue(
              "match_mode",
              (value as ListFormValues["match_mode"]) || "exact"
            )
          }
        />
      </Box>

      <Box>
        <Checkbox
          label='Case sensitive'
          size='sm'
          {...form.getInputProps("case_sensitive", { type: "checkbox" })}
        />
      </Box>
    </Stack>
  );
};
