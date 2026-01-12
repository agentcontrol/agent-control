import { Box, useMantineColorScheme } from "@mantine/core";
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
    <Box
      style={{
        border: `1px solid ${colorScheme === "dark" ? "#373A40" : "#e0e0e0"}`,
        borderRadius: "4px",
        padding: "12px",
        backgroundColor: colorScheme === "dark" ? "#25262B" : "#fafafa",
        minHeight,
        maxHeight,
        overflow: "auto",
      }}
    >
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
    </Box>
  );
};
