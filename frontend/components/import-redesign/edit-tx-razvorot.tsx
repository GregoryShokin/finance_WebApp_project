'use client';

/**
 * Deep editor for a single import row — opens as a "razvorot" pop-out modal
 * triggered from the pencil button in <TxRow> or per-row in cluster modal.
 *
 * Mirrors tx-row.tsx's per-type controls but laid out vertically:
 *   - 6 type chips: regular / transfer / debt / refund / investment / credit_operation
 *   - investment direction is auto-derived from row direction (no input)
 *   - credit_operation has a kind selector (disbursement / payment / early_repayment),
 *     credit account picker, and principal/interest inputs (validated to sum to total)
 *   - debt direction options are filtered by row direction
 *
 * The modal self-fetches accounts / debt partners / counterparties so both
 * callers (attention-feed, import-fab-cluster, cluster-grid) work without
 * extra plumbing — react-query dedupes the requests against shared cache.
 */

import { useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'framer-motion';
import { Loader2, X } from 'lucide-react';
import { toast } from 'sonner';

import {
  AccountSelect,
  CategorySelect,
  DebtPartnerSelect,
} from '@/components/import/entity-selects';
import { CreatableSelect, type CreatableOption } from '@/components/ui/creatable-select';
import { fmtDateTime, fmtRubSigned } from './format';
import {
  TYPE_OPTIONS,
  CREDIT_KIND_OPTIONS,
  INVEST_DIR_OPTIONS,
  type MainType,
  type DebtDirection,
  type CreditKind,
  debtDirOptionsFor,
  categoryOptionsForKind,
  creditAccountOptions,
  creditKindToOperationType,
  operationTypeToCreditKind,
  investmentDirFor,
  investmentDirToOperationType,
} from './option-sets';
import { updateImportRow } from '@/lib/api/imports';
import { getAccounts } from '@/lib/api/accounts';
import { getDebtPartners } from '@/lib/api/debt-partners';
import type { ImportPreviewRow, ImportRowUpdatePayload } from '@/types/import';

function detectInitialType(opType: string | undefined): MainType {
  if (opType === 'debt') return 'debt';
  if (opType === 'transfer') return 'transfer';
  if (opType === 'refund') return 'refund';
  if (opType === 'investment_buy' || opType === 'investment_sell') return 'investment';
  if (
    opType === 'credit_disbursement' ||
    opType === 'credit_payment' ||
    opType === 'credit_early_repayment'
  ) {
    return 'credit_operation';
  }
  return 'regular';
}

export function EditTxRazvorot({
  sessionId: _sessionId,
  row,
  origin,
  options,
  onClose,
  onSuccess,
}: {
  sessionId: number;
  row: ImportPreviewRow;
  origin: { x: number; y: number };
  options: {
    categories: (CreatableOption & { kind?: 'income' | 'expense' })[];
  };
  onClose: () => void;
  /** Fired after successful save — caller may use it for optimistic removal. */
  onSuccess?: () => void;
}) {
  const queryClient = useQueryClient();
  const nd = (row.normalized_data ?? {}) as Record<string, unknown>;

  const direction: 'income' | 'expense' = (nd.direction as 'income' | 'expense') || 'expense';
  const isIncome = direction === 'income';
  const date = (nd.date as string) || (row.raw_data?.date as string) || '';
  const totalAmount = Number((nd.amount as string | number | null) ?? row.raw_data?.amount ?? 0) || 0;

  // Spec §13 (v1.20): moderator account-selector includes closed accounts.
  // Closed accounts are valid targets for orphan-transfer binding (e.g. user
  // received money from a card that has since been closed).
  const accountsQuery = useQuery({
    queryKey: ['accounts', 'with-closed'],
    queryFn: () => getAccounts({ includeClosed: true }),
  });
  const debtPartnersQuery = useQuery({ queryKey: ['debt-partners'], queryFn: getDebtPartners });

  const accountOptions = useMemo<CreatableOption[]>(
    () =>
      (accountsQuery.data ?? []).map((a) => ({
        value: String(a.id),
        label: a.is_closed ? `${a.name} (закрыт)` : a.name,
      })),
    [accountsQuery.data],
  );
  const debtPartnerOptions = useMemo<CreatableOption[]>(
    () =>
      (debtPartnersQuery.data ?? []).map((p) => ({
        value: String(p.id),
        label: p.name,
      })),
    [debtPartnersQuery.data],
  );
  const filteredCreditAccountOptions = useMemo(
    () => creditAccountOptions(accountOptions, accountsQuery.data ?? []),
    [accountOptions, accountsQuery.data],
  );

  // ── State ──────────────────────────────────────────────────────────────
  const initialOpType = (nd.operation_type as string) || 'regular';
  const [type, setType] = useState<MainType>(detectInitialType(initialOpType));
  const [categoryId, setCategoryId] = useState<number | null>(
    (nd.category_id as number | null) ?? null,
  );
  const [description, setDescription] = useState<string>(
    (nd.description as string) || (row.raw_data?.description as string) || '',
  );
  const [debtDirection, setDebtDirection] = useState<DebtDirection | ''>(
    ((nd.debt_direction as DebtDirection) || ''),
  );
  const [debtPartnerId, setDebtPartnerId] = useState<number | null>(
    (nd.debt_partner_id as number | null) ?? null,
  );
  const [transferAccountId, setTransferAccountId] = useState<number | null>(
    (nd.target_account_id as number | null) ?? null,
  );
  const [creditKind, setCreditKind] = useState<CreditKind | ''>(
    operationTypeToCreditKind(initialOpType),
  );
  const [creditAccountId, setCreditAccountId] = useState<number | null>(
    (nd.credit_account_id as number | null) ?? null,
  );
  const [creditPrincipal, setCreditPrincipal] = useState<string>(
    ((nd.credit_principal_amount as string | number | null) ?? '').toString(),
  );
  const [creditInterest, setCreditInterest] = useState<string>(
    ((nd.credit_interest_amount as string | number | null) ?? '').toString(),
  );

  // Reset cross-type state on type switch — prevents stale ids from leaking
  // into the save payload (e.g. a debt_partner_id sticking to a transfer).
  const handleTypeChange = (next: MainType) => {
    setType(next);
    setCategoryId(null);
    setDebtPartnerId(null);
    setDebtDirection('');
    setTransferAccountId(null);
    setCreditKind('');
    setCreditAccountId(null);
    setCreditPrincipal('');
    setCreditInterest('');
  };

  const filteredCategories = useMemo(
    () =>
      categoryOptionsForKind(
        options.categories,
        type === 'refund' ? 'expense' : isIncome ? 'income' : 'expense',
      ),
    [options.categories, type, isIncome],
  );

  // ── Validation ─────────────────────────────────────────────────────────
  const creditNeedsSplit = type === 'credit_operation' && (creditKind === 'payment' || creditKind === 'early_repayment');
  const creditPrincipalNum = Number(creditPrincipal) || 0;
  const creditInterestNum = Number(creditInterest) || 0;
  const creditSum = creditPrincipalNum + creditInterestNum;
  const creditSumOk = creditNeedsSplit
    ? Math.abs(creditSum - totalAmount) < 0.005 && creditSum > 0
    : true;
  const creditTooMuch = creditNeedsSplit && creditSum > totalAmount + 0.005;

  // ── Save ───────────────────────────────────────────────────────────────
  const saveMut = useMutation({
    mutationFn: (payload: ImportRowUpdatePayload) => updateImportRow(row.id, payload),
    onSuccess: async () => {
      toast.success('Сохранено');
      // Await all refetches so that any parent cluster modal's rowsById is
      // fresh before onClose() fires. Without await the parent sees stale
      // normalized_data (user_confirmed_at absent, op_type='regular') and
      // isBulkEligible incorrectly includes this row in the next bulk-apply,
      // overwriting the just-saved debt/transfer type with 'regular'.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['imports', 'preview'] }),
        queryClient.invalidateQueries({ queryKey: ['imports', 'moderation-status'] }),
        queryClient.invalidateQueries({ queryKey: ['imports', 'bulk-clusters'] }),
      ]);
      onSuccess?.();
      onClose();
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось сохранить'),
  });

  const handleSave = () => {
    // Per-type validation gates.
    if (type === 'transfer' && !transferAccountId) {
      toast.error('Выбери счёт-получатель');
      return;
    }
    if (type === 'debt') {
      if (!debtDirection) {
        toast.error('Выбери направление долга');
        return;
      }
      if (!debtPartnerId) {
        toast.error('Выбери дебитора / кредитора');
        return;
      }
    }
    if (type === 'credit_operation') {
      if (!creditKind) {
        toast.error('Выбери направление кредита');
        return;
      }
      if (!creditAccountId) {
        toast.error('Выбери кредитный счёт');
        return;
      }
      if (creditNeedsSplit && !creditSumOk) {
        toast.error(
          creditTooMuch
            ? 'Сумма частей больше платежа'
            : 'Сумма процентов и тела долга должна совпадать с суммой операции',
        );
        return;
      }
    }
    if ((type === 'regular' || type === 'refund') && categoryId == null) {
      toast.error('Выбери категорию');
      return;
    }

    const payload: ImportRowUpdatePayload = { description, action: 'confirm' };
    if (type === 'debt') {
      payload.operation_type = 'debt';
      payload.debt_partner_id = debtPartnerId;
      payload.debt_direction = debtDirection || undefined;
      payload.category_id = null;
      payload.counterparty_id = null;
    } else if (type === 'transfer') {
      payload.operation_type = 'transfer';
      payload.target_account_id = transferAccountId;
      payload.category_id = null;
      payload.counterparty_id = null;
    } else if (type === 'investment') {
      payload.operation_type = investmentDirToOperationType(investmentDirFor(direction));
      payload.category_id = null;
      payload.counterparty_id = null;
    } else if (type === 'credit_operation') {
      payload.operation_type = creditKindToOperationType(creditKind as CreditKind);
      payload.credit_account_id = creditAccountId;
      payload.category_id = null;
      payload.counterparty_id = null;
      if (creditNeedsSplit) {
        payload.credit_principal_amount = creditPrincipalNum;
        payload.credit_interest_amount = creditInterestNum;
      }
    } else if (type === 'refund') {
      payload.operation_type = 'refund';
      payload.category_id = categoryId;
    } else {
      payload.operation_type = 'regular';
      payload.category_id = categoryId;
    }
    saveMut.mutate(payload);
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
          className="pointer-events-auto flex max-h-[88vh] w-[min(560px,92vw)] flex-col overflow-hidden rounded-3xl border border-line bg-bg-surface shadow-modal"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold text-ink">
                {(nd.description as string) || (row.raw_data?.description as string) || '(без описания)'}
              </div>
              <div className="mt-1 font-mono text-[11px] text-ink-3">
                #{row.row_index} · {fmtDateTime(date)} · {fmtRubSigned(totalAmount, direction)}
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

          {/* Body */}
          <div className="flex-1 space-y-4 overflow-auto px-5 py-5">
            {/* Type chips */}
            <div>
              <div className="mb-2 text-[11px] text-ink-3">Тип операции</div>
              <div className="flex flex-wrap gap-1.5">
                {TYPE_OPTIONS.map((t) => (
                  <button
                    key={t.value}
                    type="button"
                    onClick={() => handleTypeChange(t.value as MainType)}
                    className={
                      type === t.value
                        ? 'rounded-pill border border-accent-violet bg-accent-violet px-3 py-1.5 text-xs font-medium text-white'
                        : 'rounded-pill border border-line bg-bg-surface px-3 py-1.5 text-xs font-medium text-ink transition hover:bg-bg-surface2'
                    }
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Per-type sub-form */}
            {type === 'transfer' ? (
              <div>
                <div className="mb-1.5 text-[11px] text-ink-3">Счёт-получатель</div>
                <AccountSelect
                  value={transferAccountId}
                  options={accountOptions}
                  onChange={setTransferAccountId}
                  placeholder="— на свой счёт —"
                />
              </div>
            ) : null}

            {type === 'debt' ? (
              <>
                <div>
                  <div className="mb-1.5 text-[11px] text-ink-3">Направление</div>
                  <CreatableSelect
                    value={debtDirection}
                    options={debtDirOptionsFor(direction)}
                    onChange={(v) => setDebtDirection(v as DebtDirection)}
                    placeholder="— направление —"
                  />
                </div>
                <div>
                  <div className="mb-1.5 text-[11px] text-ink-3">Дебитор / кредитор</div>
                  <DebtPartnerSelect
                    value={debtPartnerId}
                    options={debtPartnerOptions}
                    onChange={setDebtPartnerId}
                  />
                </div>
              </>
            ) : null}

            {type === 'investment' ? (
              <div>
                <div className="mb-1.5 text-[11px] text-ink-3">Направление</div>
                <InvestmentDirBadge direction={direction} />
              </div>
            ) : null}

            {type === 'credit_operation' ? (
              <>
                <div>
                  <div className="mb-1.5 text-[11px] text-ink-3">Направление кредита</div>
                  <CreatableSelect
                    value={creditKind}
                    options={CREDIT_KIND_OPTIONS}
                    onChange={(v) => setCreditKind(v as CreditKind)}
                    placeholder="— направление кредита —"
                  />
                </div>
                <div>
                  <div className="mb-1.5 text-[11px] text-ink-3">Кредитный счёт</div>
                  <CreatableSelect
                    value={creditAccountId != null ? String(creditAccountId) : null}
                    options={filteredCreditAccountOptions}
                    onChange={(v) => setCreditAccountId(Number(v))}
                    placeholder="— кредитный счёт —"
                    emptyHint="Нет кредитных счетов"
                  />
                </div>
                {creditNeedsSplit ? (
                  <CreditPaymentDetail
                    totalAmount={totalAmount}
                    principal={creditPrincipal}
                    interest={creditInterest}
                    onPrincipalChange={setCreditPrincipal}
                    onInterestChange={setCreditInterest}
                  />
                ) : null}
              </>
            ) : null}

            {/* Category — visible for regular & refund */}
            {type === 'regular' || type === 'refund' ? (
              <div>
                <div className="mb-1.5 text-[11px] text-ink-3">Категория</div>
                <CategorySelect
                  value={categoryId}
                  options={filteredCategories}
                  onChange={setCategoryId}
                  kind={type === 'refund' ? 'expense' : isIncome ? 'income' : 'expense'}
                />
              </div>
            ) : null}

            {/* Description always visible */}
            <div>
              <div className="mb-1.5 text-[11px] text-ink-3">Описание</div>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="w-full resize-none rounded-lg border border-line bg-bg-surface px-3 py-2 font-sans text-xs text-ink outline-none focus:border-ink-3"
                rows={3}
              />
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between gap-3 border-t border-line bg-bg-surface px-5 py-4">
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
        </motion.div>
      </div>
    </AnimatePresence>,
    document.body,
  );
}

function InvestmentDirBadge({ direction }: { direction: 'income' | 'expense' | string }) {
  const v = investmentDirFor(direction);
  const o = INVEST_DIR_OPTIONS.find((x) => x.value === v) ?? INVEST_DIR_OPTIONS[0];
  return (
    <span
      title="Направление определяется автоматически по знаку операции"
      className="inline-flex h-9 items-center gap-2 rounded-lg border border-dashed border-line-strong bg-bg-surface2 px-3 text-xs text-ink-2"
    >
      <span className="size-2 shrink-0 rounded-full" style={{ background: o.toneDot }} />
      {o.label}
      <span className="text-[10.5px] text-ink-3">· авто</span>
    </span>
  );
}

function CreditPaymentDetail({
  totalAmount,
  principal,
  interest,
  onPrincipalChange,
  onInterestChange,
}: {
  totalAmount: number;
  principal: string;
  interest: string;
  onPrincipalChange: (v: string) => void;
  onInterestChange: (v: string) => void;
}) {
  const p = Number(principal) || 0;
  const i = Number(interest) || 0;
  const sum = p + i;
  const ok = Math.abs(sum - totalAmount) < 0.005 && sum > 0;
  const tooMuch = sum > totalAmount + 0.005;

  return (
    <div className="grid grid-cols-2 items-end gap-3 rounded-xl border border-line bg-bg-surface2 p-3">
      <label className="block">
        <div className="mb-1 text-[10.5px] text-ink-3">Основной долг</div>
        <input
          type="number"
          step="0.01"
          inputMode="decimal"
          value={principal}
          onChange={(e) => onPrincipalChange(e.target.value)}
          placeholder="0.00"
          className="block h-8 w-full rounded-md border border-line bg-bg-surface px-2.5 text-right font-mono text-xs outline-none focus:border-line-strong"
        />
      </label>
      <label className="block">
        <div className="mb-1 text-[10.5px] text-ink-3">Проценты</div>
        <input
          type="number"
          step="0.01"
          inputMode="decimal"
          value={interest}
          onChange={(e) => onInterestChange(e.target.value)}
          placeholder="0.00"
          className="block h-8 w-full rounded-md border border-line bg-bg-surface px-2.5 text-right font-mono text-xs outline-none focus:border-line-strong"
        />
      </label>
      <div className="col-span-2 text-[11px] leading-tight">
        <div className="text-ink-3">
          Сумма:{' '}
          <span className="font-mono">{sum.toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })} ₽</span>
          {' из '}
          <span className="font-mono">{totalAmount.toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })} ₽</span>
        </div>
        {ok ? (
          <div className="font-semibold text-accent-green">✓ Сходится</div>
        ) : tooMuch ? (
          <div className="font-semibold text-accent-red">Сумма частей больше платежа</div>
        ) : sum > 0 ? (
          <div className="font-semibold text-accent-amber">
            Не хватает {(totalAmount - sum).toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })} ₽
          </div>
        ) : (
          <div className="text-ink-3">Введи основной долг и проценты</div>
        )}
      </div>
    </div>
  );
}
