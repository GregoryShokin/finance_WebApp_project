'use client';

/**
 * Deep editor for a single import row — opens as a "razvorot" pop-out modal
 * triggered from the pencil/split button in <TxRow>. Lets the user pick a
 * detailed type, category, and write a description before confirming.
 */

import { useState } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'framer-motion';
import { Loader2, X } from 'lucide-react';
import { toast } from 'sonner';

import { CategorySelect } from '@/components/import/entity-selects';
import type { CreatableOption } from '@/components/ui/creatable-select';
import { fmtRubSigned } from './format';
import { updateImportRow } from '@/lib/api/imports';
import type { ImportPreviewRow, ImportRowUpdatePayload } from '@/types/import';

const TYPES = [
  { value: 'regular', label: 'Обычная' },
  { value: 'transfer', label: 'Перевод' },
  { value: 'debt', label: 'Долг' },
  { value: 'refund', label: 'Возврат' },
  { value: 'investment_buy', label: 'Инвестиция (покупка)' },
  { value: 'investment_sell', label: 'Инвестиция (продажа)' },
  { value: 'credit_disbursement', label: 'Выдача кредита' },
  { value: 'credit_payment', label: 'Платёж по кредиту' },
];

export function EditTxRazvorot({
  sessionId: _sessionId,
  row,
  origin,
  options,
  onClose,
}: {
  sessionId: number;
  row: ImportPreviewRow;
  origin: { x: number; y: number };
  options: { categories: CreatableOption[] };
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const nd = (row.normalized_data ?? {}) as Record<string, unknown>;

  const [opType, setOpType] = useState<string>((nd.operation_type as string) || 'regular');
  const [categoryId, setCategoryId] = useState<number | null>((nd.category_id as number | null) ?? null);
  const [description, setDescription] = useState<string>(
    (nd.description as string) || (row.raw_data?.description as string) || '',
  );

  const direction: 'income' | 'expense' = (nd.direction as 'income' | 'expense') || 'expense';
  const date = (nd.date as string) || (row.raw_data?.date as string) || '';
  const amount = (nd.amount as string | number | null) ?? row.raw_data?.amount ?? null;

  const saveMut = useMutation({
    mutationFn: (payload: ImportRowUpdatePayload) => updateImportRow(row.id, payload),
    onSuccess: () => {
      toast.success('Сохранено');
      queryClient.invalidateQueries({ queryKey: ['imports', 'preview'] });
      onClose();
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось сохранить'),
  });

  const handleSave = () => {
    saveMut.mutate({
      operation_type: opType,
      category_id: opType === 'debt' || opType === 'transfer' ? null : categoryId,
      description,
    });
  };

  return createPortal(
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1, transition: { duration: 0.18 } }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[9100] bg-ink/20 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <div className="pointer-events-none fixed inset-0 z-[9101] flex items-center justify-center p-4">
        <motion.div
          initial={{ opacity: 0, scale: 0.05 }}
          animate={{ opacity: 1, scale: 1, transition: { duration: 0.28, ease: [0.16, 0.84, 0.3, 1] } }}
          exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.14 } }}
          style={{
            transformOrigin: `${origin.x - window.innerWidth / 2}px ${origin.y - window.innerHeight / 2}px`,
          }}
          className="pointer-events-auto flex w-[min(520px,90vw)] flex-col overflow-hidden rounded-3xl border border-line bg-bg-surface shadow-modal"
          onClick={(e) => e.stopPropagation()}
        >
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-ink">
              {(nd.description as string) || (row.raw_data?.description as string) || '(без описания)'}
            </div>
            <div className="mt-1 font-mono text-[11px] text-ink-3">
              #{row.row_index} · {date} · {fmtRubSigned(amount as number | string | null | undefined, direction)}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid size-8 place-items-center rounded-full text-ink-3 transition hover:bg-ink/5"
          >
            <X className="size-3.5" />
          </button>
        </div>

        <div className="space-y-4 px-5 py-5">
          <div>
            <div className="mb-2 text-[11px] text-ink-3">Тип операции</div>
            <div className="flex flex-wrap gap-1.5">
              {TYPES.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  onClick={() => setOpType(t.value)}
                  className={
                    opType === t.value
                      ? 'rounded-pill border border-accent-violet bg-accent-violet px-3 py-1.5 text-xs font-medium text-white'
                      : 'rounded-pill border border-line bg-bg-surface px-3 py-1.5 text-xs font-medium text-ink transition hover:bg-bg-surface2'
                  }
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>

          {opType !== 'debt' && opType !== 'transfer' ? (
            <div>
              <div className="mb-1.5 text-[11px] text-ink-3">Категория</div>
              <CategorySelect
                value={categoryId}
                options={options.categories}
                onChange={setCategoryId}
                kind={direction === 'income' ? 'income' : 'expense'}
              />
            </div>
          ) : null}

          <div>
            <div className="mb-1.5 text-[11px] text-ink-3">Описание</div>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full resize-none rounded-lg border border-line bg-bg-surface px-3 py-2 font-sans text-xs text-ink outline-none focus:border-ink-3"
              rows={3}
            />
          </div>

          <div className="flex items-center justify-between pt-2">
            <span className="text-[11px] text-ink-3">
              Сохранение перезапишет нормализованные значения этой строки.
            </span>
            <button
              type="button"
              disabled={saveMut.isPending}
              onClick={handleSave}
              className="inline-flex items-center gap-2 rounded-lg bg-ink px-4 py-2 text-xs font-medium text-white transition hover:bg-ink-2 disabled:opacity-60"
            >
              {saveMut.isPending ? <Loader2 className="size-3 animate-spin" /> : null}
              Готово
            </button>
          </div>
        </div>
        </motion.div>
      </div>
    </AnimatePresence>,
    document.body,
  );
}
