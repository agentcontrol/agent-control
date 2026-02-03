import { Checkbox, Select, Stack, Textarea } from "@mantine/core";

import {
  labelPropsInline,
  LabelWithTooltip,
} from "@/core/components/label-with-tooltip";

import type { EvaluatorFormProps } from "../types";
import type { ListFormValues } from "./types";

export const ListForm = ({ form }: EvaluatorFormProps<ListFormValues>) => {
  return (
    <Stack gap="md">
      <Textarea
        label={
          <LabelWithTooltip
            label="Values"
            tooltip="List of values to match against (one per line)"
          />
        }
        labelProps={labelPropsInline}
        placeholder="Enter values (one per line)"
        minRows={4}
        maxRows={8}
        autosize
        size="sm"
        {...form.getInputProps("values")}
      />

      <Select
        label={
          <LabelWithTooltip
            label="Logic"
            tooltip="How to combine multiple values when matching"
          />
        }
        labelProps={labelPropsInline}
        data={[
          { value: "any", label: "Any (match if any value matches)" },
          { value: "all", label: "All (match if all values match)" },
        ]}
        size="sm"
        {...form.getInputProps("logic")}
        onChange={(value) =>
          form.setFieldValue("logic", (value as ListFormValues["logic"]) || "any")
        }
      />

      <Select
        label={
          <LabelWithTooltip
            label="Match on"
            tooltip="Whether to trigger when value matches or when it does not match"
          />
        }
        labelProps={labelPropsInline}
        data={[
          { value: "match", label: "Match (trigger when matched)" },
          { value: "no_match", label: "No match (trigger when not matched)" },
        ]}
        size="sm"
        {...form.getInputProps("match_on")}
        onChange={(value) =>
          form.setFieldValue(
            "match_on",
            (value as ListFormValues["match_on"]) || "match"
          )
        }
      />

      <Select
        label={
          <LabelWithTooltip
            label="Match mode"
            tooltip="Exact string match or substring (contains)"
          />
        }
        labelProps={labelPropsInline}
        data={[
          { value: "exact", label: "Exact (full string match)" },
          { value: "contains", label: "Contains (substring match)" },
        ]}
        size="sm"
        {...form.getInputProps("match_mode")}
        onChange={(value) =>
          form.setFieldValue(
            "match_mode",
            (value as ListFormValues["match_mode"]) || "exact"
          )
        }
      />

      <Checkbox
        label="Case sensitive"
        size="sm"
        {...form.getInputProps("case_sensitive", { type: "checkbox" })}
      />
    </Stack>
  );
};
