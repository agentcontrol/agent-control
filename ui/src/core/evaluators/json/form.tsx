import {
  Box,
  Checkbox,
  Divider,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";

import type { EvaluatorFormProps } from "../types";
import type { JsonFormValues } from "./types";

export const JsonForm = ({ form }: EvaluatorFormProps<JsonFormValues>) => {
  return (
    <Stack gap='md'>
      <Divider label='Schema Validation' labelPosition='left' />

      <Box>
        <Text size='sm' fw={500} mb={4}>
          JSON Schema
        </Text>
        <Textarea
          placeholder='{"type": "object", "properties": {...}}'
          minRows={4}
          maxRows={10}
          autosize
          styles={{ input: { fontFamily: "monospace" } }}
          {...form.getInputProps("json_schema")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          JSON Schema specification (Draft 7 or later) for structure validation
        </Text>
      </Box>

      <Divider label='Field Validation' labelPosition='left' />

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Required fields
        </Text>
        <TextInput
          placeholder='field1, nested.field, data.items'
          {...form.getInputProps("required_fields")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Comma-separated list of required field paths (supports dot notation)
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Field types
        </Text>
        <Textarea
          placeholder='{"name": "string", "age": "integer", "active": "boolean"}'
          minRows={3}
          maxRows={8}
          autosize
          styles={{ input: { fontFamily: "monospace" } }}
          {...form.getInputProps("field_types")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          JSON mapping of field paths to expected types (string, number,
          integer, boolean, array, object, null)
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Field constraints
        </Text>
        <Textarea
          placeholder='{"price": {"min": 0, "max": 10000}, "status": {"enum": ["active", "inactive"]}}'
          minRows={3}
          maxRows={8}
          autosize
          styles={{ input: { fontFamily: "monospace" } }}
          {...form.getInputProps("field_constraints")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          JSON mapping of field paths to constraints (min/max for numbers, enum
          for allowed values, min_length/max_length for strings)
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Field patterns
        </Text>
        <Textarea
          placeholder='{"email": "^[a-z]+@[a-z]+\\.[a-z]+$", "phone": {"pattern": "^\\d{10}$", "flags": ["IGNORECASE"]}}'
          minRows={3}
          maxRows={8}
          autosize
          styles={{ input: { fontFamily: "monospace" } }}
          {...form.getInputProps("field_patterns")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          JSON mapping of field paths to regex patterns (RE2 syntax). Can be
          string or object with pattern and flags
        </Text>
      </Box>

      <Divider label='Validation Behavior' labelPosition='left' />

      <Box>
        <Checkbox
          label='Allow extra fields'
          size='sm'
          {...form.getInputProps("allow_extra_fields", { type: "checkbox" })}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Allow fields not defined in field_types (if unchecked, extra fields
          cause validation failure)
        </Text>
      </Box>

      <Box>
        <Checkbox
          label='Allow null for required fields'
          size='sm'
          {...form.getInputProps("allow_null_required", { type: "checkbox" })}
        />
        <Text size='xs' c='dimmed' mt={4}>
          If unchecked, null values in required fields are treated as missing
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Pattern match logic
        </Text>
        <Select
          data={[
            { value: "all", label: "All (all patterns must match)" },
            { value: "any", label: "Any (at least one pattern must match)" },
          ]}
          size='sm'
          {...form.getInputProps("pattern_match_logic")}
          onChange={(value) =>
            form.setFieldValue(
              "pattern_match_logic",
              (value as JsonFormValues["pattern_match_logic"]) || "all"
            )
          }
        />
        <Text size='xs' c='dimmed' mt={4}>
          Logic for field_patterns validation
        </Text>
      </Box>

      <Box>
        <Checkbox
          label='Case sensitive enums'
          size='sm'
          {...form.getInputProps("case_sensitive_enums", { type: "checkbox" })}
        />
        <Text size='xs' c='dimmed' mt={4}>
          If unchecked, enum matching is case-insensitive
        </Text>
      </Box>

      <Divider label='Error Handling' labelPosition='left' />

      <Box>
        <Checkbox
          label='Allow invalid JSON'
          size='sm'
          {...form.getInputProps("allow_invalid_json", { type: "checkbox" })}
        />
        <Text size='xs' c='dimmed' mt={4}>
          If checked, invalid JSON is treated as non-match (pass through). If
          unchecked, invalid JSON triggers the control
        </Text>
      </Box>
    </Stack>
  );
};
