import { PageShell } from '@/components/layout/page-shell';
import { LoadingState } from '@/components/states/page-state';

export default function TransactionsLoading() {
  return (
    <PageShell
      title="Транзакции"
      description="Загружаем страницу транзакций и готовим данные."
    >
      <LoadingState title="Открываем транзакции..." description="Подключаем список операций и фильтры." />
    </PageShell>
  );
}
