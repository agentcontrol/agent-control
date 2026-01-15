import { Paper, ScrollArea, useMantineColorScheme } from "@mantine/core";
import { JsonEditor as JsonEditReactEditor } from "json-edit-react";

import { DARK_THEME, LIGHT_THEME } from "./theme";

interface JsonEditorProps {
  data: any;
  setData: (data: any) => void;
  rootName?: string;
  restrictEdit?: boolean;
  restrictDelete?: boolean;
  restrictAdd?: boolean;
  collapse?: boolean | number;
  rootFontSize?: number;
  minHeight?: string;
  maxHeight?: string;
}

export const JsonEditor = ({
  data,
  setData,
  rootName = "root",
  restrictEdit = false,
  restrictDelete = false,
  restrictAdd = false,
  collapse = false,
  rootFontSize = 12,
  minHeight = "400px",
  maxHeight = "500px",
}: JsonEditorProps) => {
  const { colorScheme } = useMantineColorScheme();

  return (
    <Paper
      bd={`1px solid ${colorScheme === "dark" ? "#373A40" : "#e0e0e0"}`}
      radius='sm'
      p={12}
      bg={colorScheme === "dark" ? "#25262B" : "#fafafa"}
    >
      <ScrollArea mah={maxHeight} mih={minHeight} type='auto'>
        <JsonEditReactEditor
          data={data}
          setData={setData}
          rootName={rootName}
          restrictEdit={restrictEdit}
          restrictDelete={restrictDelete}
          restrictAdd={restrictAdd}
          collapse={collapse}
          rootFontSize={rootFontSize}
          theme={colorScheme === "dark" ? DARK_THEME : LIGHT_THEME}
        />
      </ScrollArea>
    </Paper>
  );
};
