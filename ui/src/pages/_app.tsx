// Import Mantine styles
import '@mantine/core/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/charts/styles.css';
import '@mantine/code-highlight/styles.css';
import '@mantine/notifications/styles.css';
// Import jupiter-ds styles
import '@rungalileo/jupiter-ds/styles.css';
// Import rungalileo icons styles
import '@rungalileo/icons/styles.css';
// Import global styles
import '@/styles/globals.css';

import { MantineProvider } from '@mantine/core';
import { DatesProvider } from '@mantine/dates';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { JupiterThemeProvider } from '@rungalileo/jupiter-ds';
import type { AppProps } from 'next/app';
import Head from 'next/head';

import { ErrorBoundary } from '@/components/error-boundary';
import { QueryProvider } from '@/core/providers/query-provider';
import type { NextPageWithLayout } from '@/core/types/page';

type AppPropsWithLayout = AppProps & {
  Component: NextPageWithLayout;
};

// Custom theme override to use Inter and Fira Mono fonts

export default function App({ Component, pageProps }: AppPropsWithLayout) {
  // Use the layout defined at the page level, or default to no layout
  const getLayout = Component.getLayout ?? ((page) => page);

  return (
    <>
      <Head>
        {/* Viewport */}
        <meta
          content="minimum-scale=1, initial-scale=1, width=device-width"
          name="viewport"
        />

        {/* Canonical URL */}
        <link
          rel="canonical"
          href="https://github.com/agentcontrol/agent-control"
        />

        {/* Favicons */}
        <link href="/ac-icon.jpg" rel="icon" type="image/jpeg" />
        <link href="/ac-icon.jpg" rel="apple-touch-icon" sizes="180x180" />
        <link href="/site.webmanifest" rel="manifest" />
        <link color="#644DF9" href="/safari-pinned-tab.svg" rel="mask-icon" />

        {/* SEO Meta Tags */}
        <title>Agent Control - Runtime Guardrails for AI Agents</title>
        <meta
          name="description"
          content="Production-ready runtime guardrails for AI agents. Policy-based control layer that blocks harmful content, prompt injections, and PII leakage without changing your code."
        />
        <meta
          name="keywords"
          content="AI agents, guardrails, runtime safety, prompt injection, PII detection, agent control, AI safety, policy enforcement, production AI"
        />
        <meta name="author" content="Agent Control" />

        {/* Open Graph / Facebook */}
        <meta property="og:type" content="website" />
        <meta
          property="og:url"
          content="https://github.com/agentcontrol/agent-control"
        />
        <meta
          property="og:title"
          content="Agent Control - Runtime Guardrails for AI Agents"
        />
        <meta
          property="og:description"
          content="Policy-based control layer for AI agents. Block harmful content, prompt injections, and PII leakage in production."
        />
        <meta property="og:site_name" content="Agent Control" />

        {/* Twitter */}
        <meta name="twitter:card" content="summary_large_image" />
        <meta
          name="twitter:title"
          content="Agent Control - Runtime Guardrails for AI Agents"
        />
        <meta
          name="twitter:description"
          content="Policy-based control layer for AI agents. Block harmful content, prompt injections, and PII leakage in production."
        />

        {/* Theme Color */}
        <meta name="theme-color" content="#644DF9" />
      </Head>

      <ErrorBoundary variant="page">
        <QueryProvider>
          <MantineProvider defaultColorScheme="auto">
            <Notifications />
            <DatesProvider settings={{ firstDayOfWeek: 0 }}>
              <JupiterThemeProvider>
                <ModalsProvider>
                  {getLayout(<Component {...pageProps} />)}
                </ModalsProvider>
              </JupiterThemeProvider>
            </DatesProvider>
          </MantineProvider>
        </QueryProvider>
      </ErrorBoundary>
    </>
  );
}
