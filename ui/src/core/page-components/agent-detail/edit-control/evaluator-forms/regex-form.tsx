import { Box, Stack, Text, TextInput } from "@mantine/core";

import type { RegexFormProps } from "../types";

export const RegexForm = ({ form }: RegexFormProps) => {
  return (
    <Stack gap='md'>
      <Box>
        <Text size='sm' fw={500} mb={4}>
          Pattern
        </Text>
        <TextInput
          placeholder='Enter regex pattern (e.g., ^.*$)'
          styles={{ input: { fontFamily: "monospace" } }}
          {...form.getInputProps("pattern")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Regular expression pattern to match against
        </Text>
      </Box>
    </Stack>
  );
};
