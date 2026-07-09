import type { ReactElement } from 'react';

import { DEFENSECLAW_SYNC_AGENT_NAME } from '@/core/constants/defenseclaw';
import { AppLayout } from '@/core/layouts/app-layout';
import AgentDetailPage from '@/core/page-components/agent-detail/agent-detail';
import type { NextPageWithLayout } from '@/core/types/page';

const ControlsPage: NextPageWithLayout = () => (
  <AgentDetailPage
    agentId={DEFENSECLAW_SYNC_AGENT_NAME}
    standaloneTab="controls"
  />
);

ControlsPage.getLayout = (page: ReactElement) => <AppLayout>{page}</AppLayout>;

export default ControlsPage;
