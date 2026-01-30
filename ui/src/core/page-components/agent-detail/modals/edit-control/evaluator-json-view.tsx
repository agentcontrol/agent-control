import {
  Box,
  // Group,
  ScrollArea,
  // SegmentedControl,
  Textarea,
} from "@mantine/core";

import { JsonEditor } from "@/components/json-editor";

import type { EvaluatorJsonViewProps } from "./types";

const DEFAULT_HEIGHT = 400;

export const EvaluatorJsonView = ({
  config,
  onChange,
  jsonViewMode,
  onJsonViewModeChange: _onJsonViewModeChange,
  rawJsonText,
  onRawJsonTextChange,
  rawJsonError,
  height = DEFAULT_HEIGHT,
}: EvaluatorJsonViewProps) => {
  // TODO: Re-enable tree/raw toggle when needed
  // <Group justify='flex-end'>
  //   <SegmentedControl
  //     value={jsonViewMode}
  //     onChange={handleModeChange}
  //     data={[
  //       { value: "tree", label: "Tree" },
  //       { value: "raw", label: "Raw" },
  //     ]}
  //     size='xs'
  //   />
  // </Group>

  if (jsonViewMode === "tree") {
    return (
      <ScrollArea h={height} type="auto">
        <Box p="xs">
          <JsonEditor
            data={config}
            setData={onChange}
            rootName="config"
            restrictEdit={false}
            restrictDelete={false}
            restrictAdd={false}
            collapse={false}
            rootFontSize={12}
          />
        </Box>
      </ScrollArea>
    );
  }

  return (
    <Textarea
      value={rawJsonText}
      onChange={(e) => onRawJsonTextChange(e.currentTarget.value)}
      styles={{
        input: {
          fontFamily: "monospace",
          fontSize: 12,
          height,
          overflow: "auto",
        },
      }}
      error={rawJsonError}
      data-testid="raw-json-textarea"
    />
  );
};
