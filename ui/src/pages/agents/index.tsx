import { Box, Center, Loader, Stack, Text } from '@mantine/core';
import { useRouter } from 'next/router';
import { type ReactElement, useEffect } from 'react';

import { AppLayout } from '@/core/layouts/app-layout';
import AgentDetailPage from '@/core/page-components/agent-detail/agent-detail';
import type { NextPageWithLayout } from '@/core/types/page';

const AgentPage: NextPageWithLayout = () => {
  const router = useRouter();
  const { id, tab } = router.query;

  useEffect(() => {
    if (router.isReady && typeof id !== 'string') {
      void router.replace('/');
    }
  }, [id, router]);

  if (!router.isReady || typeof id !== 'string') {
    return (
      <Box p="xl" maw={1400} mx="auto" my={0}>
        <Center h={400}>
          <Stack align="center" gap="md">
            <Loader size="lg" />
            <Text c="dimmed">Loading...</Text>
          </Stack>
        </Center>
      </Box>
    );
  }

  const defaultTab = tab === 'controls' || tab === 'monitor' ? tab : undefined;

  return <AgentDetailPage agentId={id} defaultTab={defaultTab} />;
};

AgentPage.getLayout = (page: ReactElement) => {
  return <AppLayout>{page}</AppLayout>;
};

export default AgentPage;
