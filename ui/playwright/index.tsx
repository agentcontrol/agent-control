import '@mantine/charts/styles.css';
import '@mantine/code-highlight/styles.css';
import '@mantine/core/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/notifications/styles.css';
import '@rungalileo/icons/styles.css';
import '@rungalileo/jupiter-ds/styles.css';
import '@/styles/globals.css';

import { MantineProvider } from '@mantine/core';
import { DatesProvider } from '@mantine/dates';
import { ModalsProvider } from '@mantine/modals';
import { beforeMount } from '@playwright/experimental-ct-react/hooks';
import { JupiterThemeProvider } from '@rungalileo/jupiter-ds';

import { appTheme } from '@/theme';

beforeMount(async ({ App }) => (
  <MantineProvider theme={appTheme} defaultColorScheme="light">
    <DatesProvider settings={{ firstDayOfWeek: 0 }}>
      <JupiterThemeProvider>
        <ModalsProvider>
          <App />
        </ModalsProvider>
      </JupiterThemeProvider>
    </DatesProvider>
  </MantineProvider>
));
