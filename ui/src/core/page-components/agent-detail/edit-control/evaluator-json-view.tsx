import { Group, SegmentedControl, Stack, Textarea } from "@mantine/core";

import { JsonEditor } from "@/components/json-editor";

import type { EvaluatorJsonViewProps, JsonViewMode } from "./types";

export const EvaluatorJsonView = ({
  config,
  onChange,
  jsonViewMode,
  onJsonViewModeChange,
  rawJsonText,
  onRawJsonTextChange,
  rawJsonError,
}: EvaluatorJsonViewProps) => {
  const handleModeChange = (value: string) => {
    onJsonViewModeChange(value as JsonViewMode);
  };

  return (
    <Stack gap='sm'>
      {/* Tree/Raw sub-toggle */}
      <Group justify='flex-end'>
        <SegmentedControl
          value={jsonViewMode}
          onChange={handleModeChange}
          data={[
            { value: "tree", label: "Tree" },
            { value: "raw", label: "Raw" },
          ]}
          size='xs'
        />
      </Group>

      {jsonViewMode === "tree" ? (
        <JsonEditor
          data={config}
          setData={onChange}
          rootName='config'
          restrictEdit={false}
          restrictDelete={false}
          restrictAdd={false}
          collapse={false}
          rootFontSize={12}
          minHeight='400px'
          maxHeight='500px'
        />
      ) : (
        <Textarea
          value={rawJsonText}
          onChange={(e) => onRawJsonTextChange(e.currentTarget.value)}
          minRows={15}
          maxRows={20}
          autosize
          styles={{
            input: {
              fontFamily: "monospace",
              fontSize: 12,
            },
          }}
          error={rawJsonError}
          data-testid='raw-json-textarea'
        />
      )}
    </Stack>
  );
};
