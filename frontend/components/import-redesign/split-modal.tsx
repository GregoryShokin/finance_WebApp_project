'use client';

/**
 * SplitModal — divide a single import row into N parts.
 *
 * Supported part types (backed by ImportSplitItemRequest):
 *   regular  → category_id required
 *   refund   → category_id required
 *   transfer → target_account_id required
 *   debt     → debt_direction + debt_partner_id required
 *   investment → no extra fields (direction inferred from row)
 *
 * Credit operations (credit_disbursement / credit_early_repayment) are
 * intentionally disabled — ImportSplitItemRequest lacks credit_account_id.
 */

import { useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'framer-motion';
import { Loader2, Plus, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';

import { CreatableSelect, type CreatableOption } from '@/components/ui/creatable-select';
import { CategorySelect, AccountSelect, DebtPartnerSelect } from '@/components/import/entity-selects';
import { fmtRubAbs } from './format';
import {
  TYPE_OPTIONS,
  categoryOptionsForKind,
  debtDirOptionsFor,
  investmentDirFor,
  investmentDirToOperationType,
  type MainType,
  type DebtDirection,
  DEBT_DIR_OPTIONS,
} from './option-sets';
import { updateImportRow } from '@/lib/api/imports';
import { getAccounts } from '@/lib/api/accounts';
import { getDebtPartners } from '@/lib/api/debt-partners';
import type { ImportPreviewRow, ImportSplitItem } from '@/types/import';

// Credit types are not yet supported in splits (missing credit_account_id in schema).
const CREDIT_TYPES = new Set(['credit_operation', 'credit_disbursement', 'credit_payment', 'credit_early_repayment']);

type Part = {
  uid: string;
  type: MainType;
  amount: string;
  description: string;
  // regular / refund
  category_id: number | null;
  // transfer
  target_account_id: number | null;
  // debt
  debt_direction: DebtDirection | '';
  debt_partner_id: number | null;
};

function makeEmptyPart(): Part {
  return {
    uid: Math.random().toString(36).slice(2),
    type: 'regular',
    amount: '',
    description: '',
    category_id: null,
    target_account_id: null,
    debt_direction: '',
    debt_partner_id: null,
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
  onSuccess?: () => void;
}) {
  const queryClient = useQueryClient();
  const nd = (row.normalized_data ?? {}) as Record<string, unknown>;
  const direction: 'income' | 'expense' = (nd.direction as 'income' | 'expense') || 'expense';
  const isIncome = direction === 'income';
  const total = Number((nd.amount as string | number | null) ?? row.raw_data?.amount ?? 0) || 0;
  const desc = (nd.description as string) || (row.raw_data?.description as string) || '(без описания)';

  // Fetch accounts and debt partners for the new type-specific selectors.
  const accountsQuery = useQuery({ queryKey: ['accounts'], queryFn: getAccounts });
  const debtPartnersQuery = useQuery({ queryKey: ['debt-partners'], queryFn: getDebtPartners });

  const accountOptions = useMemo<CreatableOption[]>(
    () => (accountsQuery.data ?? []).map((a) => ({ value: String(a.id), label: a.name })),
    [accountsQuery.data],
  );
  const debtPartnerOptions = useMemo<CreatableOption[]>(
    () => (debtPartnersQuery.data ?? []).map((p) => ({ value: String(p.id), label: p.name })),
    [debtPartnersQuery.data],
  );

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
    updatePart(last.uid, { amount: ((Number(last.amount) || 0) + diff).toFixed(2) });
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
    if (valid.length < 2) { toast.error('Нужно минимум 2 части с суммой больше 0'); return; }
    if (!sumOk) { toast.error('Сумма частей должна совпадать с суммой операции'); return; }

    for (const p of valid) {
      if ((p.type === 'regular' || p.type === 'refund') && !p.category_id) {
        toast.error(`Часть "${p.description || p.type}": выбери категорию`); return;
      }
      if (p.type === 'transfer' && !p.target_account_id) {
        toast.error(`Часть "${p.description || 'Перевод'}": выбери счёт назначения`); return;
      }
      if (p.type === 'debt' && (!p.debt_direction || !p.debt_partner_id)) {
        toast.error(`Часть "${p.description || 'Долг'}": укажи направление и партнёра`); return;
      }
    }

    const split_items: ImportSplitItem[] = valid.map((p) => {
      // Map UI type to backend operation_type.
      let op: string = p.type;
      if (p.type === 'investment') {
        op = investmentDirToOperationType(investmentDirFor(direction));
      }
      return {
        operation_type: op,
        amount: Number(p.amount),
        description: p.description?.trim() || null,
        category_id: p.category_id ?? null,
        target_account_id: p.target_account_id ?? null,
        debt_direction: p.debt_direction || null,
        debt_partner_id: p.debt_partner_id ?? null,
      };
    });
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
          <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-ink">Разделить операцию</div>
              <div className="mt-1 truncate text-xs text-ink-3">
                {desc} · {fmtRubAbs(total)}
              </div>
            </div>
            <button type="button" onClick={onClose}
              className="grid size-8 place-items-center rounded-full text-ink-3 transition hover:bg-ink/5">
              <X className="size-3.5" />
            </button>
          </header>

          <div className="flex-1 overflow-auto px-5 pb-3 pt-3">
            {parts.map((p, idx) => (
              <PartCard
                key={p.uid}
                part={p}
                index={idx}
                canRemove={parts.length > 1}
                isIncome={isIncome}
                categoryOptions={options.categories}
                accountOptions={accountOptions}
                debtPartnerOptions={debtPartnerOptions}
                onChange={(patch) => updatePart(p.uid, patch)}
                onRemove={() => removePart(p.uid)}
              />
            ))}
            <button type="button" onClick={addPart}
              className="flex h-9 w-full items-center justify-center gap-1.5 rounded-lg border border-line bg-bg-surface text-xs font-medium text-ink-2 transition hover:bg-bg-surface2">
              <Plus className="size-3.5" /> Добавить часть
            </button>
          </div>

          <footer className="flex items-center justify-between gap-3 border-t border-line bg-bg-surface2 px-5 py-3">
            <div className="text-xs text-ink-2">
              <div>
                Сумма частей: <span className="font-mono font-semibold">{fmtRubAbs(totalParts)}</span>{' '}
                из <span className="font-mono font-semibold">{fmtRubAbs(total)}</span>
              </div>
              {sumOk ? (
                <span className="text-[11px] text-accent-green">✓ Сходится</span>
              ) : Math.abs(diff) >= 0.005 ? (
                <button type="button" onClick={distributeRemainder}
                  className="mt-1 text-[11px] text-ink-3 underline-offset-2 hover:underline">
                  Дозаполнить остаток ({fmtRubAbs(diff)}) в последнюю часть
                </button>
              ) : null}
            </div>
            <button type="button" disabled={submitMut.isPending} onClick={handleSubmit}
              className="inline-flex items-center gap-2 rounded-lg bg-ink px-4 py-2 text-xs font-medium text-white transition hover:bg-ink-2 disabled:cursor-not-allowed disabled:opacity-60">
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
  accountOptions,
  debtPartnerOptions,
  onChange,
  onRemove,
}: {
  part: Part;
  index: number;
  canRemove: boolean;
  isIncome: boolean;
  categoryOptions: (CreatableOption & { kind?: 'income' | 'expense' })[];
  accountOptions: CreatableOption[];
  debtPartnerOptions: CreatableOption[];
  onChange: (patch: Partial<Part>) => void;
  onRemove: () => void;
}) {
  const partKind: 'income' | 'expense' = part.type === 'refund' ? 'expense' : (isIncome ? 'income' : 'expense');
  const partCategoryOptions = useMemo(
    () => categoryOptionsForKind(categoryOptions, partKind),
    [categoryOptions, partKind],
  );
  const debtDirOptions = useMemo(() => debtDirOptionsFor(isIncome ? 'income' : 'expense'), [isIncome]);

  // Build type options: disable credit types (schema not widened yet).
  const splitTypeOptions = TYPE_OPTIONS.map((t) => {
    if (CREDIT_TYPES.has(t.value)) {
      return { ...t, hint: 'недоступно для разделения' };
    }
    return t;
  });

  const needsCategory = part.type === 'regular' || part.type === 'refund';
  const needsAccount  = part.type === 'transfer';
  const needsDebt     = part.type === 'debt';

  return (
    <div className="mb-2.5 rounded-xl border border-line bg-bg-surface p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold text-ink">Часть #{index + 1}</span>
        <button type="button" onClick={onRemove} disabled={!canRemove}
          className="grid size-7 place-items-center rounded-md text-ink-3 transition hover:bg-bg-surface2 hover:text-accent-red disabled:cursor-not-allowed disabled:opacity-40"
          title="Удалить часть">
          <Trash2 className="size-3.5" />
        </button>
      </div>

      {/* Row 1: amount + type */}
      <div className="grid items-end gap-2 sm:grid-cols-[120px_1fr]">
        <label className="block">
          <div className="mb-1 text-[10.5px] text-ink-3">Сумма</div>
          <input
            type="number" step="0.01" inputMode="decimal"
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
              if (CREDIT_TYPES.has(v)) {
                toast.info('Кредитные операции пока не поддерживаются в разделении');
                return;
              }
              onChange({
                type: v as MainType,
                category_id: null,
                target_account_id: null,
                debt_direction: '',
                debt_partner_id: null,
              });
            }}
            width="100%"
          />
        </div>
      </div>

      {/* Row 2: type-specific fields */}
      {needsCategory ? (
        <div className="mt-2">
          <div className="mb-1 text-[10.5px] text-ink-3">Категория</div>
          <CategorySelect
            value={part.category_id}
            options={partCategoryOptions}
            onChange={(id) => onChange({ category_id: id })}
            kind={partKind}
            placeholder="— выбрать —"
          />
        </div>
      ) : null}

      {needsAccount ? (
        <div className="mt-2">
          <div className="mb-1 text-[10.5px] text-ink-3">Счёт назначения</div>
          <AccountSelect
            value={part.target_account_id}
            options={accountOptions}
            onChange={(id) => onChange({ target_account_id: id })}
            placeholder="— выбрать счёт —"
          />
        </div>
      ) : null}

      {needsDebt ? (
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <div>
            <div className="mb-1 text-[10.5px] text-ink-3">Направление долга</div>
            <CreatableSelect
              value={part.debt_direction}
              options={debtDirOptions}
              onChange={(v) => onChange({ debt_direction: v as DebtDirection })}
              width="100%"
              placeholder="— выбрать —"
            />
          </div>
          <div>
            <div className="mb-1 text-[10.5px] text-ink-3">Партнёр</div>
            <DebtPartnerSelect
              value={part.debt_partner_id}
              options={debtPartnerOptions}
              onChange={(id) => onChange({ debt_partner_id: id })}
              placeholder="— выбрать —"
            />
          </div>
        </div>
      ) : null}

      {/* Description always last */}
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
