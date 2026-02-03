import {
  Box,
  Divider,
  NumberInput,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";

import type { EvaluatorFormProps } from "../types";
import type { Luna2FormValues } from "./types";

export const Luna2Form = ({ form }: EvaluatorFormProps<Luna2FormValues>) => {
  const isLocalStage = form.values.stage_type === "local";

  return (
    <Stack gap='md'>
      <Box>
        <Text size='sm' fw={500} mb={4}>
          Stage type
        </Text>
        <Select
          data={[
            { value: "local", label: "Local (define rules at runtime)" },
            {
              value: "central",
              label: "Central (reference pre-defined stages)",
            },
          ]}
          size='sm'
          {...form.getInputProps("stage_type")}
          onChange={(value) =>
            form.setFieldValue(
              "stage_type",
              (value as Luna2FormValues["stage_type"]) || "local"
            )
          }
        />
        <Text size='xs' c='dimmed' mt={4}>
          Local: define rules at runtime. Central: reference pre-defined stages
          in Galileo
        </Text>
      </Box>

      {isLocalStage ? (
        <>
          <Divider label='Local Stage Configuration' labelPosition='left' />

          <Box>
            <Text size='sm' fw={500} mb={4}>
              Metric
            </Text>
            <Select
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
              size='sm'
              placeholder='Select a metric'
              {...form.getInputProps("metric")}
              onChange={(value) =>
                form.setFieldValue(
                  "metric",
                  (value as Luna2FormValues["metric"]) || ""
                )
              }
            />
            <Text size='xs' c='dimmed' mt={4}>
              The Galileo Luna-2 metric to evaluate (required for local stage)
            </Text>
          </Box>

          <Box>
            <Text size='sm' fw={500} mb={4}>
              Operator
            </Text>
            <Select
              data={[
                { value: "gt", label: "> (greater than)" },
                { value: "gte", label: ">= (greater than or equal)" },
                { value: "lt", label: "< (less than)" },
                { value: "lte", label: "<= (less than or equal)" },
                { value: "eq", label: "= (equal)" },
                { value: "contains", label: "Contains" },
                { value: "any", label: "Any" },
              ]}
              size='sm'
              placeholder='Select an operator'
              {...form.getInputProps("operator")}
              onChange={(value) =>
                form.setFieldValue(
                  "operator",
                  (value as Luna2FormValues["operator"]) || ""
                )
              }
            />
            <Text size='xs' c='dimmed' mt={4}>
              Comparison operator for the threshold (required for local stage)
            </Text>
          </Box>

          <Box>
            <Text size='sm' fw={500} mb={4}>
              Target value
            </Text>
            <TextInput
              placeholder='0.5'
              {...form.getInputProps("target_value")}
            />
            <Text size='xs' c='dimmed' mt={4}>
              Threshold value for comparison. Can be a number (e.g., 0.5) or
              string depending on metric (required for local stage)
            </Text>
          </Box>
        </>
      ) : (
        <>
          <Divider label='Central Stage Configuration' labelPosition='left' />

          <Box>
            <Text size='sm' fw={500} mb={4}>
              Stage name
            </Text>
            <TextInput
              placeholder='production-guard'
              {...form.getInputProps("stage_name")}
            />
            <Text size='xs' c='dimmed' mt={4}>
              Name of the pre-defined stage in Galileo (required for central
              stage)
            </Text>
          </Box>

          <Box>
            <Text size='sm' fw={500} mb={4}>
              Stage version
            </Text>
            <NumberInput
              placeholder='Leave empty for latest'
              min={1}
              {...form.getInputProps("stage_version")}
            />
            <Text size='xs' c='dimmed' mt={4}>
              Pin to a specific stage version (optional, defaults to latest)
            </Text>
          </Box>
        </>
      )}

      <Divider label='Common Settings' labelPosition='left' />

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Galileo project
        </Text>
        <TextInput
          placeholder='my-project'
          {...form.getInputProps("galileo_project")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Galileo project name for logging/organization
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Payload field
        </Text>
        <Select
          data={[
            { value: "", label: "Auto-detect" },
            { value: "input", label: "Input" },
            { value: "output", label: "Output" },
          ]}
          size='sm'
          clearable
          {...form.getInputProps("payload_field")}
          onChange={(value) =>
            form.setFieldValue(
              "payload_field",
              (value as Luna2FormValues["payload_field"]) || ""
            )
          }
        />
        <Text size='xs' c='dimmed' mt={4}>
          Which payload field to evaluate (auto-detected based on metric if not
          set)
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Timeout (ms)
        </Text>
        <NumberInput
          placeholder='10000'
          min={1000}
          max={60000}
          step={1000}
          {...form.getInputProps("timeout_ms")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Request timeout in milliseconds (1-60 seconds)
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          On error
        </Text>
        <Select
          data={[
            {
              value: "allow",
              label: "Allow (fail open - pass through on error)",
            },
            { value: "deny", label: "Deny (fail closed - block on error)" },
          ]}
          size='sm'
          {...form.getInputProps("on_error")}
          onChange={(value) =>
            form.setFieldValue(
              "on_error",
              (value as Luna2FormValues["on_error"]) || "allow"
            )
          }
        />
        <Text size='xs' c='dimmed' mt={4}>
          Action to take when evaluation encounters an error
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Metadata
        </Text>
        <Textarea
          placeholder='{"key": "value"}'
          minRows={2}
          maxRows={6}
          autosize
          styles={{ input: { fontFamily: "monospace" } }}
          {...form.getInputProps("metadata")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Additional metadata to send with the request (JSON format)
        </Text>
      </Box>
    </Stack>
  );
};
