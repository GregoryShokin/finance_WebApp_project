'use client';

import { useState } from 'react';
import { PageShell } from '@/components/layout/page-shell';
import { ImportWizard } from '@/components/import/import-wizard';
import { ImportQueue } from '@/components/import/import-queue';
import { AccountFreshnessBlock } from '@/components/import/account-freshness-block';

export default function Page() {
  const [resumeSessionId, setResumeSessionId] = useState<number | undefined>();

  return (
    <PageShell
      title="Импорт выписок"
      description="Загрузи выписку из банка — система распознает структуру и импортирует транзакции."
    >
      <div className="space-y-6">
        <AccountFreshnessBlock />
        <ImportWizard
          key={resumeSessionId ?? 'new'}
          initialSessionId={resumeSessionId}
          onSessionCreated={() => setResumeSessionId(undefined)}
          sidebar={(
            <div className="space-y-3">
              <div>
                <h3 className="text-sm font-semibold text-slate-900">Очередь выписок</h3>
                <p className="mt-1 text-xs text-slate-500">
                  Выписки ожидающие проверки. Нажми чтобы продолжить.
                </p>
              </div>
              <ImportQueue onResume={(id) => setResumeSessionId(id)} />
            </div>
          )}
        />
      </div>
    </PageShell>
  );
}
