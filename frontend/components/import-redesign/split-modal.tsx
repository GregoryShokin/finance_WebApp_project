'use client';

/**
 * SplitModal — divide a single import row into N parts.
 *
 * Backend contract (current): ImportSplitItem = { category_id, amount, description }.
 * That means split_items only support **regular / refund** parts. Other UI
 * types (debt / transfer / credit / investment) are disabled here and will
 * become available once the backend ImportSplitItem schema is widened.
 *
 * On confirm we call updateImportRow with `split_items` populated; the
 * preview refresh then surfaces the parts in <SplitChip>.
 */

import { useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'framer-motion';
import { Loader2, Plus, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';

import { CreatableSelect, type CreatableOption } from '@/components/ui/creatable-select';
import { CategorySelect } from '@/components/import/entity-selects';
import { fmtRubAbs } from './format';
import {
  TYPE_OPTIONS,
  categoryOptionsForKind,
  type MainType,
} from './option-sets';
import { updateImportRow } from '@/lib/api/imports';
import type { ImportPreviewRow, ImportSplitItem } from '@/types/import';

type PartType = 'regular' | 'refund';

type Part = {
  uid: string;
  type: PartType;
  amount: string;
  category_id: number | null;
  description: string;
};

const SUPPORTED_PART_TYPES = new Set<MainType>(['regular', 'refund']);

function makeEmptyPart(): Part {
  return {
    uid: Math.random().toString(36).slice(2),
    type: 'regular',
    amount: '',
    category_id: null,
    description: '',
  };
}

export function SplitModal({
  row,
  origin,
  options,
  onClose,
  onSuccess,
}: {
  row: ImportPreviewRow;
  origin: { x: number; y: number };
  options: {
    categories: (CreatableOption & { kind?: 'income' | 'expense' })[];
  };
  onClose: () => void;
  /** Optional callback fired after the row is committed via split.
   *  Caller may use this to optimistically remove the row from a parent list. */
  onSuccess?: () => void;
}) {
  const queryClient = useQueryClient();
  const nd = (row.normalized_data ?? {}) as Record<string, unknown>;
  const direction: 'income' | 'expense' = (nd.direction as 'income' | 'expense') || 'expense';
  const isIncome = direction === 'income';
  const total = Number((nd.amount as string | number | null) ?? row.raw_data?.amount ?? 0) || 0;
  const desc = (nd.description as string) || (row.raw_data?.description as string) || '(без описания)';

  const [parts, setParts] = useState<Part[]>([makeEmptyPart(), makeEmptyPart()]);

  const totalParts = useMemo(
    () => parts.reduce((s, p) => s + (Number(p.amount) || 0), 0),
    [parts],
  );
  const diff = total - totalParts;
  const sumOk = Math.abs(diff) < 0.005 && totalParts > 0;

  const updatePart = (uid: string, patch: Partial<Part>) =>
    setParts((arr) => arr.map((p) => (p.uid === uid ? { ...p, ...patch } : p)));
  const addPart = () => setParts((arr) => [...arr, makeEmptyPart()]);
  const removePart = (uid: string) =>
    setParts((arr) => (arr.length > 1 ? arr.filter((p) => p.uid !== uid) : arr));
  const distributeRemainder = () => {
    if (parts.length === 0 || Math.abs(diff) < 0.005) return;
    const last = parts[parts.length - 1];
    updatePart(last.uid, {
      amount: ((Number(last.amount) || 0) + diff).toFixed(2),
    });
  };

  const submitMut = useMutation({
    mutationFn: (split_items: ImportSplitItem[]) =>
      updateImportRow(row.id, { split_items, action: 'confirm' }),
    onSuccess: () => {
      toast.success('Операция разделена');
      queryClient.invalidateQueries({ queryKey: ['imports', 'preview'] });
      queryClient.invalidateQueries({ queryKey: ['imports', 'moderation-status'] });
      queryClient.invalidateQueries({ queryKey: ['imports', 'bulk-clusters'] });
      onSuccess?.();
      onClose();
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось разделить операцию'),
  });

  const handleSubmit = () => {
    const valid = parts.filter((p) => Number(p.amount) > 0);
    if (valid.length < 2) {
      toast.error('Нужно минимум 2 части с суммой больше 0');
      return;
    }
    if (valid.some((p) => p.category_id == null)) {
      toast.error('У каждой части должна быть категория');
      return;
    }
    if (!sumOk) {
      toast.error('Сумма частей должна совпадать с суммой операции');
      return;
    }
    const split_items: ImportSplitItem[] = valid.map((p) => ({
      category_id: p.category_id as number,
      amount: Number(p.amount),
      description: p.description?.trim() || null,
    }));
    submitMut.mutate(split_items);
  };

  return createPortal(
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1, transition: { duration: 0.18 } }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[9000] bg-ink/30 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <div className="pointer-events-none fixed inset-0 z-[9001] flex items-center justify-center p-4">
        <motion.div
          initial={{ opacity: 0, scale: 0.05 }}
          animate={{ opacity: 1, scale: 1, transition: { duration: 0.32, ease: [0.16, 0.84, 0.3, 1] } }}
          exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.14 } }}
          style={{
            transformOrigin: `${origin.x - window.innerWidth / 2}px ${origin.y - window.innerHeight / 2}px`,
          }}
          className="pointer-events-auto flex max-h-[85vh] w-[min(720px,92vw)] flex-col overflow-hidden rounded-3xl border border-line bg-bg-surface shadow-modal"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-ink">Разделить операцию</div>
              <div className="mt-1 truncate text-xs text-ink-3">
                {desc} · {fmtRubAbs(total)}
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="grid size-8 place-items-center rounded-full text-ink-3 transition hover:bg-ink/5"
            >
              <X className="size-3.5" />
            </button>
          </header>

          {/* Parts list */}
          <div className="flex-1 overflow-auto px-5 pb-3 pt-3">
            {parts.map((p, idx) => (
              <PartCard
                key={p.uid}
                part={p}
                index={idx}
                canRemove={parts.length > 1}
                isIncome={isIncome}
                categoryOptions={options.categories}
                onChange={(patch) => updatePart(p.uid, patch)}
                onRemove={() => removePart(p.uid)}
              />
            ))}
            <button
              type="button"
              onClick={addPart}
              className="flex h-9 w-full items-center justify-center gap-1.5 rounded-lg border border-line bg-bg-surface text-xs font-medium text-ink-2 transition hover:bg-bg-surface2"
            >
              <Plus className="size-3.5" /> Добавить часть
            </button>
          </div>

          {/* Footer */}
          <footer className="flex items-center justify-between gap-3 border-t border-line bg-bg-surface2 px-5 py-3">
            <div className="text-xs text-ink-2">
              <div>
                Сумма частей: <span className="font-mono font-semibold">{fmtRubAbs(totalParts)}</span> из{' '}
                <span className="font-mono font-semibold">{fmtRubAbs(total)}</span>
              </div>
              {sumOk ? (
                <span className="text-[11px] text-accent-green">✓ Сходится</span>
              ) : Math.abs(diff) >= 0.005 ? (
                <button
                  type="button"
                  onClick={distributeRemainder}
                  className="mt-1 text-[11px] text-ink-3 underline-offset-2 hover:underline"
                >
                  Дозаполнить остаток ({fmtRubAbs(diff)}) в последнюю часть
                </button>
              ) : null}
            </div>
            <button
              type="button"
              disabled={submitMut.isPending}
              onClick={handleSubmit}
              className="inline-flex items-center gap-2 rounded-lg bg-ink px-4 py-2 text-xs font-medium text-white transition hover:bg-ink-2 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitMut.isPending ? <Loader2 className="size-3 animate-spin" /> : null}
              Применить разделение
            </button>
          </footer>
        </motion.div>
      </div>
    </AnimatePresence>,
    document.body,
  );
}

// ──────────────────────────────────────────────────────────────────────────

function PartCard({
  part,
  index,
  canRemove,
  isIncome,
  categoryOptions,
  onChange,
  onRemove,
}: {
  part: Part;
  index: number;
  canRemove: boolean;
  isIncome: boolean;
  categoryOptions: (CreatableOption & { kind?: 'income' | 'expense' })[];
  onChange: (patch: Partial<Part>) => void;
  onRemove: () => void;
}) {
  // Refund parts are always against expense categories.
  const partKind: 'income' | 'expense' = part.type === 'refund' ? 'expense' : (isIncome ? 'income' : 'expense');
  const partCategoryOptions = useMemo(
    () => categoryOptionsForKind(categoryOptions, partKind),
    [categoryOptions, partKind],
  );

  // Disable types that require a richer split_item schema on the backend.
  const splitTypeOptions = TYPE_OPTIONS.map((t) => {
    if (SUPPORTED_PART_TYPES.has(t.value as MainType)) return t;
    return { ...t, hint: 'недоступно для разделения' };
  });

  return (
    <div className="mb-2.5 rounded-xl border border-line bg-bg-surface p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold text-ink">Часть #{index + 1}</span>
        <button
          type="button"
          onClick={onRemove}
          disabled={!canRemove}
          className="grid size-7 place-items-center rounded-md text-ink-3 transition hover:bg-bg-surface2 hover:text-accent-red disabled:cursor-not-allowed disabled:opacity-40"
          title="Удалить часть"
        >
          <Trash2 className="size-3.5" />
        </button>
      </div>

      <div className="grid items-end gap-2 lg:grid-cols-[120px_1fr_1fr]">
        <label className="block">
          <div className="mb-1 text-[10.5px] text-ink-3">Сумма</div>
          <input
            type="number"
            step="0.01"
            inputMode="decimal"
            value={part.amount}
            onChange={(e) => onChange({ amount: e.target.value })}
            placeholder="0.00"
            className="block h-8 w-full rounded-md border border-line bg-bg-surface px-2.5 text-right font-mono text-xs outline-none focus:border-line-strong"
          />
        </label>
        <div>
          <div className="mb-1 text-[10.5px] text-ink-3">Тип</div>
          <CreatableSelect
            value={part.type}
            options={splitTypeOptions}
            onChange={(v) => {
              if (!SUPPORTED_PART_TYPES.has(v as MainType)) {
                toast.info('Этот тип пока не поддержан в разделении — нужен бэкенд-апдейт ImportSplitItem');
                return;
              }
              onChange({ type: v as PartType, category_id: null });
            }}
            width="100%"
          />
        </div>
        <div>
          <div className="mb-1 text-[10.5px] text-ink-3">Категория</div>
          <CategorySelect
            value={part.category_id}
            options={partCategoryOptions}
            onChange={(id) => onChange({ category_id: id })}
            kind={partKind}
            placeholder="— выбрать —"
          />
        </div>
      </div>

      <div className="mt-2">
        <div className="mb-1 text-[10.5px] text-ink-3">Описание (опционально)</div>
        <input
          type="text"
          value={part.description}
          onChange={(e) => onChange({ description: e.target.value })}
          placeholder="Например: «билеты в кино»"
          className="block h-8 w-full rounded-md border border-line bg-bg-surface px-2.5 text-xs outline-none focus:border-line-strong"
        />
      </div>
    </div>
  );
}
