'use client';

import { useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { PageShell } from '@/components/layout/page-shell';
import { Card } from '@/components/ui/card';

export default function TransactionsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('Transactions route error:', error);
  }, [error]);

  return (
    <PageShell
      title="Транзакции"
      description="Во время открытия страницы произошла ошибка. Попробуй перезагрузить данные."
    >
      <Card className="rounded-2xl border border-rose-200 bg-white p-6 shadow-soft">
        <div className="space-y-3">
          <h3 className="text-base font-semibold text-slate-950">Страница транзакций временно недоступна</h3>
          <p className="text-sm text-slate-500">
            {error.message || 'Произошла неизвестная ошибка при инициализации страницы.'}
          </p>
          <Button onClick={reset}>Повторить</Button>
        </div>
      </Card>
    </PageShell>
  );
}
