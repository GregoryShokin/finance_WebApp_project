'use client';

import { useState } from 'react';
import { PageShell } from '@/components/layout/page-shell';
import { ImportWizard } from '@/components/import/import-wizard';
import { ImportQueue } from '@/components/import/import-queue';
import { AccountFreshnessBlock } from '@/components/import/account-freshness-block';

export default function Page() {
  // Resume хранится с nonce, чтобы повторный клик на ТУ ЖЕ сессию в очереди
  // тоже триггерил пересоздание ImportWizard (через key) и заново запускал
  // auto-preview. Без nonce setState с тем же id — это no-op в React, и
  // wizard думает, что ничего не изменилось.
  const [resume, setResume] = useState<{ id: number; nonce: number } | undefined>();

  return (
    <PageShell
      title="Импорт выписок"
      description="Загрузи выписку из банка — система распознает структуру и импортирует транзакции."
    >
      <div className="space-y-6">
        <AccountFreshnessBlock />
        <ImportWizard
          key={resume ? `${resume.id}-${resume.nonce}` : 'new'}
          initialSessionId={resume?.id}
          onSessionCreated={() => setResume(undefined)}
          sidebar={(
            <div className="space-y-3">
              <div>
                <h3 className="text-sm font-semibold text-slate-900">Очередь выписок</h3>
                <p className="mt-1 text-xs text-slate-500">
                  Выписки ожидающие проверки. Нажми чтобы продолжить.
                </p>
              </div>
              <ImportQueue onResume={(id) => setResume({ id, nonce: Date.now() })} />
            </div>
          )}
        />
      </div>
    </PageShell>
  );
}
