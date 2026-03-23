import { PageShell } from '@/components/layout/page-shell';
import { ImportWizard } from '@/components/import/import-wizard';

export default function Page() {
  return (
    <PageShell
      title="Импорт источников транзакций"
      description="Загрузи CSV, XLSX или PDF, проверь распознавание структуры, при необходимости подтверди поля и только потом импортируй транзакции."
    >
      <ImportWizard />
    </PageShell>
  );
}
