import './globals.css';
import type { Metadata } from 'next';
import { AppProvider } from '@/components/providers/app-provider';

// Fonts are loaded via Google Fonts CDN (matches the design mockup):
//   • Geist            — primary UI sans
//   • Instrument Serif — decorative headings ("Распределение операций")
//   • JetBrains Mono   — tabular numbers / monospace IDs
// CDN gives consistent rendering for Cyrillic that the standalone `geist`
// package didn't cover, which is why the in-app text felt different from the
// HTML mockup. Variables (--font-sans / --font-serif / --font-mono) are still
// the contract — Tailwind's `font-sans` / `font-serif` / `font-mono` resolve
// through them.

export const metadata: Metadata = {
  title: 'FinanceApp — учёт личных финансов',
  description: 'Веб-приложение для учёта личных финансов, счетов, категорий и транзакций.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=Instrument+Serif&family=JetBrains+Mono:wght@400;500&display=swap"
        />
      </head>
      <body className="font-sans">
        <AppProvider>{children}</AppProvider>
      </body>
    </html>
  );
}
