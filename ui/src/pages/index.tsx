import type { ReactElement } from 'react';

import { DEFENSECLAW_SYNC_AGENT_NAME } from '@/core/constants/defenseclaw';
import { AppLayout } from '@/core/layouts/app-layout';
import AgentDetailPage from '@/core/page-components/agent-detail/agent-detail';
import HomePage from '@/core/page-components/home/home';
import { useAuth } from '@/core/providers/auth-provider';
import type { NextPageWithLayout } from '@/core/types/page';

const AgentsPage: NextPageWithLayout = () => {
  const { auth } = useAuth();

  if (auth.status === 'authenticated') {
    return (
      <AgentDetailPage
        agentId={DEFENSECLAW_SYNC_AGENT_NAME}
        standaloneTab="controls"
      />
    );
  }
  return <HomePage />;
};

// Attach layout to page
AgentsPage.getLayout = (page: ReactElement) => {
  return <AppLayout>{page}</AppLayout>;
};

export default AgentsPage;
