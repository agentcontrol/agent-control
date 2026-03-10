import { ColorSchemeScript } from '@mantine/core';
import { Head, Html, Main, NextScript } from 'next/document';

import { inter } from '@/styles/fonts';

export default function Document() {
  return (
    <Html lang="en">
      <Head>
        <ColorSchemeScript defaultColorScheme="auto" />
        <link rel="icon" href="/ac-logo-dark.svg" type="image/svg+xml" />
        <link rel="mask-icon" href="/safari-pinned-tab.svg" color="#644DF9" />
        <link rel="manifest" href="/site.webmanifest" />
      </Head>
      <body className={inter.className}>
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
