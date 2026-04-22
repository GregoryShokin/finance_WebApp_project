"use client";

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import { PageShell } from '@/components/layout/page-shell';
import { EmptyState, ErrorState, LoadingState } from '@/components/states/page-state';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { StatCard } from '@/components/shared/stat-card';
import { getParkedQueue, unparkImportRow } from '@/lib/api/imports';
import type { ParkedQueueItem } from '@/types/import';

export default function Page() {
  const queryClient = useQueryClient();

  const queueQuery = useQuery({
    queryKey: ['imports', 'parked-queue'],
    queryFn: () => getParkedQueue(),
  });

  const unparkMutation = useMutation({
    mutationFn: (rowId: number) => unparkImportRow(rowId),
    onSuccess: () => {
      toast.success('Строка возвращена в очередь на разбор');
      queryClient.invalidateQueries({ queryKey: ['imports', 'parked-queue'] });
    },
    onError: (error: Error) => {
      toast.error(`Не удалось вернуть строку: ${error.message}`);
    },
  });

  return (
    <PageShell
      title="Недоразобранное"
      description="Строки, которые вы отложили из импортов. Они не попадают в аналитику до тех пор, пока вы не вернёте их в очередь и не разберёте."
    >
      <div className="grid gap-4 md:grid-cols-2">
        <StatCard label="Всего в очереди" value={String(queueQuery.data?.total ?? 0)} />
        <StatCard label="Из разных сессий" value={countUniqueSessions(queueQuery.data?.items ?? [])} />
      </div>

      <Card className="p-5">
        {queueQuery.isLoading ? (
          <LoadingState />
        ) : queueQuery.error ? (
          <ErrorState title="Не удалось загрузить очередь" description={String(queueQuery.error)} />
        ) : !queueQuery.data?.items.length ? (
          <EmptyState
            title="Ничего не отложено"
            description="Когда вы отложите строку из импорта кнопкой «Отложить», она появится здесь. Возврат вернёт её в очередь wizard-а."
          />
        ) : (
          <div className="space-y-3">
            {queueQuery.data.items.map((item) => (
              <ParkedRow
                key={item.row_id}
                item={item}
                onUnpark={() => unparkMutation.mutate(item.row_id)}
                disabled={unparkMutation.isPending}
              />
            ))}
          </div>
        )}
      </Card>
    </PageShell>
  );
}

function ParkedRow({
  item,
  onUnpark,
  disabled,
}: {
  item: ParkedQueueItem;
  onUnpark: () => void;
  disabled: boolean;
}) {
  const description =
    (item.normalized_data?.description as string | undefined) ??
    (item.normalized_data?.import_original_description as string | undefined) ??
    '—';
  const amount = item.normalized_data?.amount as string | number | undefined;
  const date =
    (item.normalized_data?.transaction_date as string | undefined) ??
    (item.normalized_data?.date as string | undefined);

  return (
    <div className="flex flex-col items-start justify-between gap-3 rounded-2xl border border-slate-100 bg-white p-4 lg:flex-row lg:items-center">
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium text-slate-900" title={String(description)}>
          {description}
        </div>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
          <span>Файл: {item.filename}</span>
          {amount !== undefined ? <span>Сумма: {amount}</span> : null}
          {date ? <span>Дата: {String(date).slice(0, 10)}</span> : null}
          <span>Строка #{item.row_index}</span>
        </div>
      </div>
      <Button variant="secondary" onClick={onUnpark} disabled={disabled}>
        <RotateCcw className="size-4" />
        Вернуть в разбор
      </Button>
    </div>
  );
}

function countUniqueSessions(items: ParkedQueueItem[]): string {
  return String(new Set(items.map((i) => i.session_id)).size);
}
