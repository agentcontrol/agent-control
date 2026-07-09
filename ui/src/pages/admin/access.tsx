import type { ReactElement } from 'react';

import { AppLayout } from '@/core/layouts/app-layout';
import AccessManagementPage from '@/core/page-components/access-management/access-management';
import type { NextPageWithLayout } from '@/core/types/page';

const AccessPage: NextPageWithLayout = () => <AccessManagementPage />;

AccessPage.getLayout = (page: ReactElement) => <AppLayout>{page}</AppLayout>;

export default AccessPage;
