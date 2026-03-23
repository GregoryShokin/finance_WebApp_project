import { PageShell } from '@/components/layout/page-shell';
import { SectionPlaceholder } from '@/components/layout/section-placeholder';

export default function Page() {
  return (
    <PageShell title="Банковские подключения" description="Раздел для будущей интеграции с банками и автоматической синхронизации транзакций.">
      <SectionPlaceholder
        title="Каркас для bank connections готов"
        description="Единый стиль уже подготовлен. На следующем этапе сюда можно добавить список подключений, статусы синхронизации, кнопки переподключения и историю импорта."
      />
    </PageShell>
  );
}
