'use client';

/**
 * BrandCreateModal — «+ Создать бренд» from a single ImportRow.
 *
 * Flow:
 *   1. On open, fetch /brands/suggest-from-row?row_id=<row.id>. Server runs
 *      brand_extractor on skeleton + reads sbp_merchant_id token; returns
 *      (canonical_name, pattern_kind, pattern_value) prefill.
 *   2. User edits name / category / pattern (all optional overrides).
 *   3. Submit chains:
 *        POST /brands                    → brand_id
 *        POST /brands/{id}/patterns      → adds the chosen pattern
 *        POST /imports/rows/{id}/confirm-brand → confirms on source row
 *        POST /brands/{id}/apply-to-session    → bulk-confirms session siblings
 *      Each call's failure stops the chain with a toast; on success we
 *      invalidate the preview/bulk-clusters queries and close.
 */

import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { CategorySelect } from '@/components/import/entity-selects';
import type { CreatableOption } from '@/components/ui/creatable-select';
import {
  type BrandPatternKind,
  addBrandPattern,
  applyBrandToSession,
  createBrand,
  suggestBrandFromRow,
} from '@/lib/api/brands';
import { confirmRowBrand } from '@/lib/api/imports';

const PATTERN_KIND_LABEL: Record<BrandPatternKind, string> = {
  text: 'Подстрока в описании',
  sbp_merchant_id: 'SBP merchant_id',
  org_full: 'Полное название юр. лица',
  alias_exact: 'Точное совпадение',
};

export function BrandCreateModal({
  open,
  rowId,
  sessionId,
  rawDescription,
  categoryOptions,
  onClose,
}: {
  open: boolean;
  rowId: number;
  sessionId: number;
  /** Raw row description, shown read-only so the user has context. */
  rawDescription: string;
  /** Expense-kind categories shared with brand-prompt; CreatableSelect contract. */
  categoryOptions: (CreatableOption & { kind?: 'income' | 'expense' })[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();

  const [canonicalName, setCanonicalName] = useState('');
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [patternKind, setPatternKind] = useState<BrandPatternKind>('text');
  const [patternValue, setPatternValue] = useState('');

  // Prefill query — reset state on each open via the row_id key.
  const suggestQuery = useQuery({
    queryKey: ['brand-suggest-from-row', rowId],
    queryFn: () => suggestBrandFromRow(rowId),
    enabled: open && rowId > 0,
    staleTime: 0,
  });

  useEffect(() => {
    if (!suggestQuery.data) return;
    const s = suggestQuery.data;
    setCanonicalName(s.canonical_name ?? '');
    setPatternKind(s.pattern_kind ?? 'text');
    setPatternValue(s.pattern_value ?? '');
    setCategoryId(null);
  }, [suggestQuery.data]);

  const submitMut = useMutation({
    mutationFn: async () => {
      const trimmedName = canonicalName.trim();
      const trimmedPattern = patternValue.trim();
      if (!trimmedName) throw new Error('Введите название бренда');
      if (!trimmedPattern) throw new Error('Укажите паттерн распознавания');

      // 1. Create brand
      const brand = await createBrand({
        canonical_name: trimmedName,
        category_hint: null,  // category lives as per-user override, not on global Brand row
      });
      // 2. Add the chosen pattern
      await addBrandPattern(brand.id, {
        kind: patternKind,
        pattern: trimmedPattern,
        is_regex: false,
      });
      // 3. Confirm on the source row (sets counterparty + category + fingerprint)
      await confirmRowBrand(rowId, brand.id, categoryId);
      // 4. Bulk-apply to other matching rows in the same session
      const apply = await applyBrandToSession(brand.id, sessionId);
      return { brand, apply };
    },
    onSuccess: ({ brand, apply }) => {
      const extra = apply.confirmed > 0
        ? ` + ${apply.confirmed} ${pluralRows(apply.confirmed)} в сессии`
        : '';
      toast.success(`Бренд «${brand.canonical_name}» создан${extra}`);
      queryClient.invalidateQueries({ queryKey: ['imports', 'preview'] });
      queryClient.invalidateQueries({ queryKey: ['imports', 'bulk-clusters'] });
      queryClient.invalidateQueries({ queryKey: ['brand-suggested-groups'] });
      onClose();
    },
    onError: (err: Error) =>
      toast.error(err.message || 'Не удалось создать бренд'),
  });

  const isLoading = suggestQuery.isLoading;
  const isSubmitting = submitMut.isPending;
  const canSubmit =
    !isSubmitting && canonicalName.trim() !== '' && patternValue.trim() !== '';

  const patternHelp = useMemo(() => patternHelperText(patternKind), [patternKind]);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Создать бренд"
      description="Бренд приватный — виден только вам. Будет автоматически распознаваться при будущих импортах."
    >
      <div className="space-y-4">
        <div className="rounded-lg border border-line bg-bg-surface2 px-3 py-2 text-[12px] text-ink-3">
          <div className="text-[11px] uppercase tracking-wide text-ink-3">Из строки</div>
          <div className="mt-0.5 truncate text-ink">{rawDescription || '—'}</div>
        </div>

        <Field label="Название бренда">
          <input
            type="text"
            value={canonicalName}
            onChange={(e) => setCanonicalName(e.target.value)}
            disabled={isLoading || isSubmitting}
            placeholder={isLoading ? 'Загрузка…' : 'Например, Nippon Coffee'}
            className="w-full rounded-md border border-line bg-bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-60"
          />
        </Field>

        <Field
          label="Категория"
          hint="Применится ко всем строкам этого бренда. Можно изменить позже."
        >
          <CategorySelect
            value={categoryId}
            options={categoryOptions}
            onChange={setCategoryId}
            kind="expense"
            width="100%"
            disabled={isLoading || isSubmitting}
          />
        </Field>

        <Field label="Паттерн распознавания" hint={patternHelp}>
          <div className="flex gap-2">
            <select
              value={patternKind}
              onChange={(e) => setPatternKind(e.target.value as BrandPatternKind)}
              disabled={isLoading || isSubmitting}
              className="rounded-md border border-line bg-bg-surface px-2 py-2 text-xs text-ink focus:border-accent focus:outline-none disabled:opacity-60"
            >
              {Object.entries(PATTERN_KIND_LABEL).map(([k, label]) => (
                <option key={k} value={k}>{label}</option>
              ))}
            </select>
            <input
              type="text"
              value={patternValue}
              onChange={(e) => setPatternValue(e.target.value)}
              disabled={isLoading || isSubmitting}
              placeholder={isLoading ? '…' : ''}
              className="flex-1 rounded-md border border-line bg-bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-60"
            />
          </div>
        </Field>

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line pt-3">
          <Button type="button" variant="ghost" onClick={onClose} disabled={isSubmitting}>
            Отмена
          </Button>
          <Button
            type="button"
            disabled={!canSubmit}
            onClick={() => submitMut.mutate()}
          >
            {isSubmitting ? 'Создаю…' : 'Создать и привязать'}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-[11px] font-medium uppercase tracking-wide text-ink-3">{label}</span>
      <div className="mt-1">{children}</div>
      {hint ? <span className="mt-1 block text-[11px] text-ink-3">{hint}</span> : null}
    </label>
  );
}

function patternHelperText(kind: BrandPatternKind): string {
  switch (kind) {
    case 'text':
      return 'Подстрока в нормализованном описании. Чем длиннее — тем точнее. Минимум 3 символа.';
    case 'sbp_merchant_id':
      return 'Цифровой идентификатор мерчанта SBP (например, 26033). Самый точный сигнал из возможных.';
    case 'org_full':
      return 'Полное название юр. лица из выписки (включая «ООО»/«ИП»). Регистр и пробелы игнорируются.';
    case 'alias_exact':
      return 'Точное совпадение всего описания. Только для коротких алиасов («WB», «KFC»).';
  }
}

function pluralRows(n: number): string {
  const last = n % 10;
  const tens = n % 100;
  if (tens >= 11 && tens <= 14) return 'строк';
  if (last === 1) return 'строка';
  if (last >= 2 && last <= 4) return 'строки';
  return 'строк';
}
