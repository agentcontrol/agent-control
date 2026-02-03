import {
  Checkbox,
  Divider,
  Select,
  Stack,
  Textarea,
  TextInput,
} from "@mantine/core";

import {
  labelPropsInline,
  LabelWithTooltip,
} from "@/core/components/label-with-tooltip";

import type { EvaluatorFormProps } from "../types";
import type { JsonFormValues } from "./types";

export const JsonForm = ({ form }: EvaluatorFormProps<JsonFormValues>) => {
  return (
    <Stack gap="md">
      <Divider label="Schema Validation" labelPosition="left" />

      <Textarea
        label={
          <LabelWithTooltip
            label="JSON Schema"
            tooltip="JSON Schema specification (Draft 7 or later) for structure validation"
          />
        }
        labelProps={labelPropsInline}
        placeholder='{"type": "object", "properties": {...}}'
        minRows={4}
        maxRows={10}
        autosize
        size="sm"
        styles={{ input: { fontFamily: "monospace" } }}
        {...form.getInputProps("json_schema")}
      />

      <Divider label="Field Validation" labelPosition="left" />

      <TextInput
        label={
          <LabelWithTooltip
            label="Required fields"
            tooltip="Comma-separated list of required field paths (supports dot notation)"
          />
        }
        labelProps={labelPropsInline}
        placeholder="field1, nested.field, data.items"
        size="sm"
        {...form.getInputProps("required_fields")}
      />

      <Textarea
        label={
          <LabelWithTooltip
            label="Field types"
            tooltip="JSON mapping of field paths to expected types (string, number, integer, boolean, array, object, null)"
          />
        }
        labelProps={labelPropsInline}
        placeholder='{"name": "string", "age": "integer", "active": "boolean"}'
        minRows={3}
        maxRows={8}
        autosize
        size="sm"
        styles={{ input: { fontFamily: "monospace" } }}
        {...form.getInputProps("field_types")}
      />

      <Textarea
        label={
          <LabelWithTooltip
            label="Field constraints"
            tooltip="JSON mapping of field paths to constraints (min/max for numbers, enum for allowed values, min_length/max_length for strings)"
          />
        }
        labelProps={labelPropsInline}
        placeholder='{"price": {"min": 0, "max": 10000}, "status": {"enum": ["active", "inactive"]}}'
        minRows={3}
        maxRows={8}
        autosize
        size="sm"
        styles={{ input: { fontFamily: "monospace" } }}
        {...form.getInputProps("field_constraints")}
      />

      <Textarea
        label={
          <LabelWithTooltip
            label="Field patterns"
            tooltip="JSON mapping of field paths to regex patterns (RE2 syntax). Can be string or object with pattern and flags"
          />
        }
        labelProps={labelPropsInline}
        placeholder='{"email": "^[a-z]+@[a-z]+\\.[a-z]+$", "phone": {"pattern": "^\\d{10}$", "flags": ["IGNORECASE"]}}'
        minRows={3}
        maxRows={8}
        autosize
        size="sm"
        styles={{ input: { fontFamily: "monospace" } }}
        {...form.getInputProps("field_patterns")}
      />

      <Divider label="Validation Behavior" labelPosition="left" />

      <Checkbox
        label={
          <LabelWithTooltip
            label="Allow extra fields"
            tooltip="Allow fields not defined in field_types (if unchecked, extra fields cause validation failure)"
          />
        }
        size="sm"
        {...form.getInputProps("allow_extra_fields", { type: "checkbox" })}
      />

      <Checkbox
        label={
          <LabelWithTooltip
            label="Allow null for required fields"
            tooltip="If unchecked, null values in required fields are treated as missing"
          />
        }
        size="sm"
        {...form.getInputProps("allow_null_required", { type: "checkbox" })}
      />

      <Select
        label={
          <LabelWithTooltip
            label="Pattern match logic"
            tooltip="Logic for field_patterns validation"
          />
        }
        labelProps={labelPropsInline}
        data={[
          { value: "all", label: "All (all patterns must match)" },
          { value: "any", label: "Any (at least one pattern must match)" },
        ]}
        size="sm"
        {...form.getInputProps("pattern_match_logic")}
        onChange={(value) =>
          form.setFieldValue(
            "pattern_match_logic",
            (value as JsonFormValues["pattern_match_logic"]) || "all"
          )
        }
      />

      <Checkbox
        label={
          <LabelWithTooltip
            label="Case sensitive enums"
            tooltip="If unchecked, enum matching is case-insensitive"
          />
        }
        size="sm"
        {...form.getInputProps("case_sensitive_enums", { type: "checkbox" })}
      />

      <Divider label="Error Handling" labelPosition="left" />

      <Checkbox
        label={
          <LabelWithTooltip
            label="Allow invalid JSON"
            tooltip="If checked, invalid JSON is treated as non-match (pass through). If unchecked, invalid JSON triggers the control"
          />
        }
        size="sm"
        {...form.getInputProps("allow_invalid_json", { type: "checkbox" })}
      />
    </Stack>
  );
};
