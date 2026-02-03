import {
  Divider,
  NumberInput,
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
import type { Luna2FormValues } from "./types";

export const Luna2Form = ({ form }: EvaluatorFormProps<Luna2FormValues>) => {
  const isLocalStage = form.values.stage_type === "local";

  return (
    <Stack gap="md">
      <Select
        label={
          <LabelWithTooltip
            label="Stage type"
            tooltip="Local: define rules at runtime. Central: reference pre-defined stages in Galileo"
          />
        }
        labelProps={labelPropsInline}
        data={[
          { value: "local", label: "Local (define rules at runtime)" },
          {
            value: "central",
            label: "Central (reference pre-defined stages)",
          },
        ]}
        size="sm"
        {...form.getInputProps("stage_type")}
        onChange={(value) =>
          form.setFieldValue(
            "stage_type",
            (value as Luna2FormValues["stage_type"]) || "local"
          )
        }
      />

      {isLocalStage ? (
        <>
          <Divider label="Local Stage Configuration" labelPosition="left" />

          <Select
            label={
              <LabelWithTooltip
                label="Metric"
                tooltip="The Galileo Luna-2 metric to evaluate (required for local stage)"
              />
            }
            labelProps={labelPropsInline}
            data={[
              { value: "input_toxicity", label: "Input Toxicity" },
              { value: "output_toxicity", label: "Output Toxicity" },
              { value: "input_sexism", label: "Input Sexism" },
              { value: "output_sexism", label: "Output Sexism" },
              { value: "prompt_injection", label: "Prompt Injection" },
              { value: "pii_detection", label: "PII Detection" },
              { value: "hallucination", label: "Hallucination" },
              { value: "tone", label: "Tone" },
            ]}
            size="sm"
            placeholder="Select a metric"
            {...form.getInputProps("metric")}
            onChange={(value) =>
              form.setFieldValue(
                "metric",
                (value as Luna2FormValues["metric"]) || ""
              )
            }
          />

          <Select
            label={
              <LabelWithTooltip
                label="Operator"
                tooltip="Comparison operator for the threshold (required for local stage)"
              />
            }
            labelProps={labelPropsInline}
            data={[
              { value: "gt", label: "> (greater than)" },
              { value: "gte", label: ">= (greater than or equal)" },
              { value: "lt", label: "< (less than)" },
              { value: "lte", label: "<= (less than or equal)" },
              { value: "eq", label: "= (equal)" },
              { value: "contains", label: "Contains" },
              { value: "any", label: "Any" },
            ]}
            size="sm"
            placeholder="Select an operator"
            {...form.getInputProps("operator")}
            onChange={(value) =>
              form.setFieldValue(
                "operator",
                (value as Luna2FormValues["operator"]) || ""
              )
            }
          />

          <TextInput
            label={
              <LabelWithTooltip
                label="Target value"
                tooltip="Threshold value for comparison. Can be a number (e.g., 0.5) or string depending on metric (required for local stage)"
              />
            }
            labelProps={labelPropsInline}
            placeholder="0.5"
            size="sm"
            {...form.getInputProps("target_value")}
          />
        </>
      ) : (
        <>
          <Divider label="Central Stage Configuration" labelPosition="left" />

          <TextInput
            label={
              <LabelWithTooltip
                label="Stage name"
                tooltip="Name of the pre-defined stage in Galileo (required for central stage)"
              />
            }
            labelProps={labelPropsInline}
            placeholder="production-guard"
            size="sm"
            {...form.getInputProps("stage_name")}
          />

          <NumberInput
            label={
              <LabelWithTooltip
                label="Stage version"
                tooltip="Pin to a specific stage version (optional, defaults to latest)"
              />
            }
            labelProps={labelPropsInline}
            placeholder="Leave empty for latest"
            min={1}
            size="sm"
            {...form.getInputProps("stage_version")}
          />
        </>
      )}

      <Divider label="Common Settings" labelPosition="left" />

      <TextInput
        label={
          <LabelWithTooltip
            label="Galileo project"
            tooltip="Galileo project name for logging/organization"
          />
        }
        labelProps={labelPropsInline}
        placeholder="my-project"
        size="sm"
        {...form.getInputProps("galileo_project")}
      />

      <Select
        label={
          <LabelWithTooltip
            label="Payload field"
            tooltip="Which payload field to evaluate (auto-detected based on metric if not set)"
          />
        }
        labelProps={labelPropsInline}
        data={[
          { value: "", label: "Auto-detect" },
          { value: "input", label: "Input" },
          { value: "output", label: "Output" },
        ]}
        size="sm"
        clearable
        {...form.getInputProps("payload_field")}
        onChange={(value) =>
          form.setFieldValue(
            "payload_field",
            (value as Luna2FormValues["payload_field"]) || ""
          )
        }
      />

      <NumberInput
        label={
          <LabelWithTooltip
            label="Timeout (ms)"
            tooltip="Request timeout in milliseconds (1-60 seconds)"
          />
        }
        labelProps={labelPropsInline}
        placeholder="10000"
        min={1000}
        max={60000}
        step={1000}
        size="sm"
        {...form.getInputProps("timeout_ms")}
      />

      <Select
        label={
          <LabelWithTooltip
            label="On error"
            tooltip="Action to take when evaluation encounters an error"
          />
        }
        labelProps={labelPropsInline}
        data={[
          {
            value: "allow",
            label: "Allow (fail open - pass through on error)",
          },
          { value: "deny", label: "Deny (fail closed - block on error)" },
        ]}
        size="sm"
        {...form.getInputProps("on_error")}
        onChange={(value) =>
          form.setFieldValue(
            "on_error",
            (value as Luna2FormValues["on_error"]) || "allow"
          )
        }
      />

      <Textarea
        label={
          <LabelWithTooltip
            label="Metadata"
            tooltip="Additional metadata to send with the request (JSON format)"
          />
        }
        labelProps={labelPropsInline}
        placeholder='{"key": "value"}'
        minRows={2}
        maxRows={6}
        autosize
        size="sm"
        styles={{ input: { fontFamily: "monospace" } }}
        {...form.getInputProps("metadata")}
      />
    </Stack>
  );
};
