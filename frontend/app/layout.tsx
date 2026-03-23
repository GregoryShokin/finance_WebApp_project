import './globals.css';
import type { Metadata } from 'next';
import { AppProvider } from '@/components/providers/app-provider';

export const metadata: Metadata = {
  title: 'FinanceApp — учёт личных финансов',
  description: 'Веб-приложение для учёта личных финансов, счетов, категорий и транзакций.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body>
        <AppProvider>{children}</AppProvider>
      </body>
    </html>
  );
}
