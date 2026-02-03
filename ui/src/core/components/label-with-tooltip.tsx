import { Group, Text, Tooltip } from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";

export interface LabelWithTooltipProps {
  label: string;
  tooltip: string;
}

/**
 * Label with (i) icon that shows tooltip on hover.
 * Use as the `label` prop of Mantine form inputs (Select, TextInput, etc.)
 * so the input always uses the label prop and optional tooltip is consistent.
 */
export function LabelWithTooltip({ label, tooltip }: LabelWithTooltipProps) {
  return (
    <Group gap={4} wrap="nowrap" component="span" display="inline-flex">
      <Text component="span" size="sm" fw={500}>
        {label}
      </Text>
      <Tooltip label={tooltip}>
        <IconInfoCircle size={14} color="gray" style={{ display: "block" }} />
      </Tooltip>
    </Group>
  );
}

/** Pass to labelProps on inputs so the label renders inline. */
export const labelPropsInline = {
  style: { display: "inline-block" as const },
};
