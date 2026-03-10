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
import { LoginModal } from '@/core/components/login-modal';
import { AuthProvider, useAuth } from '@/core/providers/auth-provider';
import { QueryProvider } from '@/core/providers/query-provider';
import type { NextPageWithLayout } from '@/core/types/page';

type AppPropsWithLayout = AppProps & {
  Component: NextPageWithLayout;
};

// Custom theme override to use Inter and Fira Mono fonts

function AuthGate({ children }: { children: React.ReactNode }) {
  const { auth } = useAuth();

  if (auth.status === 'loading') {
    // Avoid rendering the main UI until we know whether auth is required.
    return null;
  }

  if (auth.status === 'error') {
    return (
      <div style={{ padding: 24 }}>
        <p style={{ fontWeight: 500 }}>
          Unable to connect to Agent Control server.
        </p>
        <p style={{ fontSize: 12, color: 'var(--mantine-color-dimmed)' }}>
          Check that the backend is running and reachable from this browser.
        </p>
      </div>
    );
  }

  if (auth.status === 'not-required' || auth.status === 'authenticated') {
    return <>{children}</>;
  }

  // Auth required but not satisfied: render only the login modal without the
  // underlying app, so unauthenticated users don't see the UI behind it.
  return <LoginModal opened />;
}

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
                  <AuthProvider>
                    <AuthGate>
                      {getLayout(<Component {...pageProps} />)}
                    </AuthGate>
                  </AuthProvider>
                </ModalsProvider>
              </JupiterThemeProvider>
            </DatesProvider>
          </MantineProvider>
        </QueryProvider>
      </ErrorBoundary>
    </>
  );
}
