import { Fira_Mono, Inter } from 'next/font/google';

// Font
const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  weight: 'variable',
  variable: '--font-inter',
});

const fira_mono = Fira_Mono({
  subsets: ['latin'],
  display: 'swap',
  weight: ['400', '500'],
  variable: '--font-fira-mono',
});

export { fira_mono, inter };
