import { Paper, Text } from "@mantine/core";

import type { EvaluatorConfigFormProps } from "../types";
import { ListForm } from "./list-form";
import { RegexForm } from "./regex-form";

export const EvaluatorConfigForm = ({
  pluginId,
  regexForm,
  listForm,
}: EvaluatorConfigFormProps) => {
  switch (pluginId) {
    case "regex":
      return <RegexForm form={regexForm} />;
    case "list":
      return <ListForm form={listForm} />;
    default:
      return (
        <Paper p='xl' withBorder radius='sm' ta='center'>
          <Text c='dimmed'>
            No form available for this plugin. Use JSON view to configure.
          </Text>
        </Paper>
      );
  }
};
