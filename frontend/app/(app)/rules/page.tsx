import { PageShell } from '@/components/layout/page-shell';
import { SectionPlaceholder } from '@/components/layout/section-placeholder';

export default function Page() {
  return (
    <PageShell title="Правила" description="Раздел для автоматизации: автокатегоризация, исключения и будущие AI-правила обработки транзакций.">
      <SectionPlaceholder
        title="Основа для правил уже подготовлена"
        description="После стандартизации UI этот раздел можно развивать как продуктовый модуль: список правил, приоритеты, тестирование условий и история срабатываний."
      />
    </PageShell>
  );
}
