import { Box, Center, Loader, Stack, Text } from "@mantine/core";
import { useRouter } from "next/router";
import { type ReactElement } from "react";

import { AppLayout } from "@/core/layouts/app-layout";
import AgentDetailPage from "@/core/page-components/agent-detail/agent-detail";
import type { NextPageWithLayout } from "@/core/types/page";

const AgentControlsPage: NextPageWithLayout = () => {
  const router = useRouter();
  const { id } = router.query;

  // Show loading while router is initializing
  if (!id) {
    return (
      <Box p='xl' maw={1400} mx='auto' my={0}>
        <Center h={400}>
          <Stack align='center' gap='md'>
            <Loader size='lg' />
            <Text c='dimmed'>Loading...</Text>
          </Stack>
        </Center>
      </Box>
    );
  }

  // TODO: This is a temporary fix to ensure the agent ID is a string.
  if (typeof id !== "string") {
    throw new Error("Invalid agent ID");
  }

  return <AgentDetailPage agentId={id} defaultTab="controls" />;
};

// Attach layout to page
AgentControlsPage.getLayout = (page: ReactElement) => {
  return <AppLayout>{page}</AppLayout>;
};

export default AgentControlsPage;
