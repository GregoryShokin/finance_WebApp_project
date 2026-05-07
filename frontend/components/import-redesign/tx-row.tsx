'use client';

/**
 * Single ImportPreviewRow rendered as a warm-design card with:
 *   - top: date, description, type chip (income/expense), AI-status chip, amount
 *   - middle: optional AI hint / question banner
 *   - bottom: type-aware inline selectors + traffic-light actions
 *
 * Mutates via PATCH /import/rows/{id} (updateImportRow). Maps the dropdown
 * type ("Долг"/"Перевод"/etc) to backend `operation_type`.
 */

import { type ReactNode, useCallback, useMemo, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useAnimate } from 'framer-motion';
import { Pencil, Split } from 'lucide-react';
import { toast } from 'sonner';

import { Chip } from '@/components/ui/status-chip';
import { TrafficBtn } from '@/components/ui/traffic-btn';
import { CreatableSelect, type CreatableOption } from '@/components/ui/creatable-select';
import {
  AccountSelect,
  CategorySelect,
  DebtPartnerSelect,
} from '@/components/import/entity-selects';
import { CounterpartyRazvorotButton } from './counterparty-razvorot-button';
import { fmtDateTime, fmtRubSigned } from './format';
import {
  TYPE_OPTIONS,
  type MainType,
  type DebtDirection,
  type CreditKind,
  CREDIT_KIND_OPTIONS,
  INVEST_DIR_OPTIONS,
  debtDirOptionsFor,
  categoryOptionsForKind,
  creditAccountOptions,
  creditKindToOperationType,
  operationTypeToCreditKind,
  investmentDirFor,
  investmentDirToOperationType,
} from './option-sets';
import {
  attachRowToCounterparty,
  confirmRowBrand,
  excludeImportRow,
  parkImportRow,
  rejectRowBrand,
  updateImportRow,
} from '@/lib/api/imports';
import { BrandPrompt } from './brand-prompt';
import { BrandCategoryEdit } from './brand-category-edit';
import { OrphanTransferHint } from './orphan-transfer-hint';
import type { Account } from '@/types/account';
import type { ImportPreviewRow, ImportRowUpdatePayload } from '@/types/import';
import { useFlyToFab, type FlyBucket } from './fly-to-fab-context';

function detectInitialType(row: ImportPreviewRow): MainType {
  const nd = row.normalized_data as Record<string, unknown>;
  const op = (nd?.operation_type as string) ?? 'regular';
  if (op === 'debt') return 'debt';
  if (op === 'transfer') return 'transfer';
  if (op === 'refund') return 'refund';
  if (op === 'investment_buy' || op === 'investment_sell') return 'investment';
  if (op === 'credit_disbursement' || op === 'credit_payment' || op === 'credit_early_repayment') {
    return 'credit_operation';
  }
  return 'regular';
}

type TxRowOptions = {
  categories: (CreatableOption & { kind?: 'income' | 'expense' })[];
  counterparties: CreatableOption[];
  debtPartners: CreatableOption[];
  accounts: CreatableOption[];
  accountsRaw: Account[];
};

export function TxRow({
  row,
  sessionId,
  options,
  onEditDeep,
  onSplitOpen,
}: {
  row: ImportPreviewRow;
  sessionId: number;
  options: TxRowOptions;
  onEditDeep: (origin: { x: number; y: number }) => void;
  onSplitOpen: (origin: { x: number; y: number }) => void;
}) {
  const queryClient = useQueryClient();
  const flyCtx = useFlyToFab();
  const [rowScope, rowAnimate] = useAnimate<HTMLElement>();
  const leavingRef = useRef(false);

  const triggerFly = useCallback((bucket: FlyBucket) => {
    if (leavingRef.current) return;
    leavingRef.current = true;
    const el = rowScope.current;
    if (el && flyCtx) flyCtx.flyTo(el, bucket);
    // Two-stage collapse: fade out first, then crush height.
    const h = el?.getBoundingClientRect().height ?? 0;
    if (el) {
      el.style.overflow = 'hidden';
      el.style.height = `${h}px`;
    }
    void rowAnimate(el, { opacity: 0 }, { duration: 0.1 }).then(() =>
      rowAnimate(el, { height: 0, paddingTop: 0, paddingBottom: 0 }, { duration: 0.28, ease: [0.4, 0, 0.2, 1] }),
    );
  }, [flyCtx, rowScope, rowAnimate]);

  const nd = (row.normalized_data ?? {}) as Record<string, unknown>;

  const [type, setType] = useState<MainType>(detectInitialType(row));
  const [categoryId, setCategoryId]               = useState<number | null>((nd.category_id as number | null) ?? null);
  const [counterpartyId, setCounterpartyId]       = useState<number | null>((nd.counterparty_id as number | null) ?? null);
  const [debtPartnerId, setDebtPartnerId]         = useState<number | null>((nd.debt_partner_id as number | null) ?? null);
  const [debtDirection, setDebtDirection]         = useState<DebtDirection | ''>(((nd.debt_direction as DebtDirection) || ''));
  const [transferAccountId, setTransferAccountId] = useState<number | null>((nd.target_account_id as number | null) ?? null);
  const [creditKind, setCreditKind]               = useState<CreditKind | ''>(operationTypeToCreditKind((nd.operation_type as string | undefined) ?? undefined));
  const [creditAccountId, setCreditAccountId]     = useState<number | null>((nd.credit_account_id as number | null) ?? null);
  const [creditPrincipal, setCreditPrincipal]     = useState<string>(((nd.credit_principal_amount as string | number | null) ?? '').toString());
  const [creditInterest, setCreditInterest]       = useState<string>(((nd.credit_interest_amount as string | number | null) ?? '').toString());

  // The parser stores amount as an absolute magnitude; direction is the
  // authoritative source of sign. Never derive sign from `amount > 0`.
  const direction: 'income' | 'expense' = (nd.direction as 'income' | 'expense') || 'expense';
  const amount = (nd.amount as string | number | null) ?? row.raw_data?.amount ?? null;
  const isIncome = direction === 'income';
  const date = (nd.date as string) || (row.raw_data?.date as string) || '';
  const rawDescription = (nd.description as string) || (row.raw_data?.description as string) || '';
  // Brand registry Ph7c: once user confirmed a brand for this row, show the
  // canonical brand name as the primary label and tuck the original bank
  // text underneath as a small subtitle. Pre-confirmation we keep showing
  // the bank's text so the user can read what they're confirming.
  const confirmedBrandName = nd.user_confirmed_brand_id != null
    ? (nd.brand_canonical_name as string | undefined)
    : undefined;
  const description = confirmedBrandName || rawDescription;
  const cardLast4 =
    (nd.card_last4 as string) ||
    (row.raw_data?.card as string) ||
    (nd.account_hint as string) ||
    null;

  const hint = nd.transfer_match || nd.refund_match;
  const aiQuestion =
    (nd.hypothesis as { follow_up_question?: string | null } | undefined)?.follow_up_question ?? null;

  // ── Filters ────────────────────────────────────────────────────────────
  const filteredCategoryOptions = useMemo(() => {
    const targetKind = type === 'refund' ? 'expense' : (isIncome ? 'income' : 'expense');
    return categoryOptionsForKind(options.categories, targetKind);
  }, [options.categories, type, isIncome]);

  const filteredCreditAccountOptions = useMemo(
    () => creditAccountOptions(options.accounts, options.accountsRaw),
    [options.accounts, options.accountsRaw],
  );

  // ── Mutations ────────────────────────────────────────────────────────────

  // Immediately creates a CounterpartyFingerprint binding when the user picks
  // a counterparty — this is what moves the row from AttentionFeed into the
  // counterparty group card in ClusterGrid. Selecting a counterparty is
  // treated as a standalone action, not gated on the full confirm flow.
  const attachMut = useMutation({
    mutationFn: (cpId: number) => attachRowToCounterparty(sessionId, row.id, cpId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['imports', 'bulk-clusters'] });
    },
  });

  const patchMut = useMutation({
    mutationFn: (payload: ImportRowUpdatePayload) => updateImportRow(row.id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['imports', 'preview'] });
      queryClient.invalidateQueries({ queryKey: ['imports', 'moderation-status'] });
      queryClient.invalidateQueries({ queryKey: ['imports', 'bulk-clusters'] });
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось сохранить'),
  });
  const parkMut = useMutation({
    mutationFn: () => parkImportRow(row.id),
    onSuccess: () => {
      toast.success('Отложено');
      queryClient.invalidateQueries({ queryKey: ['imports', 'preview'] });
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось отложить'),
  });
  const exclMut = useMutation({
    mutationFn: () => excludeImportRow(row.id),
    onSuccess: () => {
      toast.success('Исключено');
      queryClient.invalidateQueries({ queryKey: ['imports', 'preview'] });
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось исключить'),
  });

  // Brand registry Ph7a/Ph8: confirm/reject the resolver's prediction.
  // Confirm propagates same-brand siblings server-side; reject is row-local.
  // Ph8: when categoryId is passed, the backend saves a per-user override
  // for this brand so future imports auto-apply the chosen category.
  const brandConfirmMut = useMutation({
    mutationFn: (vars: { brandId: number; categoryId: number | null }) =>
      confirmRowBrand(row.id, vars.brandId, vars.categoryId),
    onSuccess: (resp) => {
      if (resp.propagated_count > 0) {
        toast.success(`Привязано к «${resp.brand_canonical_name}» (+${resp.propagated_count} строк)`);
      } else {
        toast.success(`Привязано к «${resp.brand_canonical_name}»`);
      }
      queryClient.invalidateQueries({ queryKey: ['imports', 'preview'] });
      queryClient.invalidateQueries({ queryKey: ['imports', 'bulk-clusters'] });
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось подтвердить бренд'),
  });
  const brandRejectMut = useMutation({
    mutationFn: () => rejectRowBrand(row.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['imports', 'preview'] });
      queryClient.invalidateQueries({ queryKey: ['imports', 'bulk-clusters'] });
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось отклонить бренд'),
  });

  const handleConfirm = () => {
    // Validate required fields before triggering animation — if validation fails
    // the row must NOT fly away (it stays visible for the user to fix).
    if ((type === 'regular' || type === 'refund') && !categoryId) {
      toast.error('Сначала выбери категорию');
      return;
    }
    if (type === 'debt' && (!debtPartnerId || !debtDirection)) {
      toast.error('Заполни направление и партнёра по долгу');
      return;
    }
    if (type === 'transfer' && !transferAccountId) {
      toast.error('Выбери счёт для перевода');
      return;
    }
    if (type === 'credit_operation' && (!creditKind || !creditAccountId)) {
      toast.error('Заполни тип и счёт кредитной операции');
      return;
    }

    triggerFly('done');
    const payload: ImportRowUpdatePayload = { action: 'confirm' };
    if (type === 'debt') {
      payload.operation_type = 'debt';
      payload.debt_partner_id = debtPartnerId;
      payload.counterparty_id = null;
      payload.category_id = null;
      if (debtDirection) payload.debt_direction = debtDirection;
    } else if (type === 'transfer') {
      payload.operation_type = 'transfer';
      payload.target_account_id = transferAccountId;
      payload.counterparty_id = null;
      payload.category_id = null;
    } else if (type === 'investment') {
      payload.operation_type = investmentDirToOperationType(investmentDirFor(direction));
      payload.counterparty_id = null;
      payload.category_id = null;
    } else if (type === 'credit_operation') {
      payload.operation_type = creditKind ? creditKindToOperationType(creditKind) : 'regular';
      payload.credit_account_id = creditAccountId;
      payload.counterparty_id = null;
      payload.category_id = null;
      if (creditKind === 'payment' || creditKind === 'early_repayment') {
        payload.credit_principal_amount = creditPrincipal ? Number(creditPrincipal) : null;
        payload.credit_interest_amount  = creditInterest  ? Number(creditInterest)  : null;
      }
    } else if (type === 'refund') {
      payload.operation_type = 'refund';
      payload.category_id = categoryId;
      payload.counterparty_id = counterpartyId;
    } else {
      payload.operation_type = 'regular';
      payload.category_id = categoryId;
      payload.counterparty_id = counterpartyId;
    }
    patchMut.mutate(payload);
  };

  const txTypeOption = TYPE_OPTIONS.find((t) => t.value === type) ?? TYPE_OPTIONS[0];
  const cpDisabled = type === 'debt' || type === 'transfer' || type === 'investment' || type === 'credit_operation';

  return (
    <article ref={rowScope} className="border-t border-line bg-bg-surface px-4 py-3.5 first:border-t-0 lg:px-5">
      {/* Top row: date + merchant + amount + status */}
      <div className="flex items-start justify-between gap-2.5">
        <div className="flex min-w-0 items-start gap-3">
          <span className="mt-0.5 shrink-0 font-mono text-[11px] text-ink-3">{fmtDateTime(date)}</span>
          <div className="min-w-0">
            <div className="text-[13px] font-medium text-ink">
              <span className="break-words">{description || '(без описания)'}</span>
              {cardLast4 ? (
                <span className="font-normal text-ink-3"> · карта {cardLast4}</span>
              ) : null}
            </div>
            {confirmedBrandName && rawDescription && rawDescription !== confirmedBrandName ? (
              <div className="mt-0.5 text-[11px] text-ink-3 break-words">
                {rawDescription}
              </div>
            ) : null}
            {confirmedBrandName ? (
              <div className="mt-1.5">
                <BrandCategoryEdit
                  brandId={Number(nd.user_confirmed_brand_id)}
                  brandName={confirmedBrandName}
                  currentCategoryId={(nd.category_id as number | null) ?? null}
                  categories={filteredCategoryOptions}
                />
              </div>
            ) : null}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Chip tone={isIncome ? 'green' : 'red'}>
            {isIncome ? '↑ доход' : '↓ расход'}
          </Chip>
          {aiQuestion ? (
            <Chip tone="blue">Нужен ответ</Chip>
          ) : row.review_required ? (
            <Chip tone="amber">Проверь</Chip>
          ) : (
            <Chip tone="green">Готово</Chip>
          )}
          <span
            className={`min-w-[90px] text-right text-sm font-semibold tabular-nums ${
              isIncome ? 'text-accent-green' : 'text-ink'
            }`}
          >
            {fmtRubSigned(amount as number | string | null | undefined, direction)}
          </span>
        </div>
      </div>

      {/* AI hints */}
      {hint && typeof hint === 'object' ? (
        <Banner tone="blue">
          {(hint as { reasoning?: string; partner_description?: string }).reasoning ||
            (hint as { partner_description?: string }).partner_description ||
            'Найден потенциальный двойник'}
        </Banner>
      ) : null}
      {aiQuestion ? <Banner tone="amber">{aiQuestion}</Banner> : null}

      {/* Brand registry Ph7a: inline «Это <brand>?» prompt.
          Visible when the resolver matched a brand above the prompt
          threshold AND the user has not yet confirmed/rejected it AND the
          row's operation is brand-bearing (regular/refund — transfers,
          debt, credit ops carry no merchant brand by design). Confirm
          propagates to same-brand siblings server-side; reject is local. */}
      {nd.brand_id != null
        && nd.user_confirmed_brand_id == null
        && nd.user_rejected_brand_id == null
        && (type === 'regular' || type === 'refund') ? (
        <BrandPrompt
          data={{
            brand_id: Number(nd.brand_id),
            brand_canonical_name: String(nd.brand_canonical_name ?? ''),
            brand_category_hint: nd.brand_category_hint
              ? String(nd.brand_category_hint)
              : null,
          }}
          // Brand prompts only fire on regular/refund rows. For refund the
          // resolved category from purchase history is expense-kind too,
          // so always show expense categories.
          categories={filteredCategoryOptions}
          isPending={brandConfirmMut.isPending || brandRejectMut.isPending}
          onConfirm={(brandId, categoryId) =>
            brandConfirmMut.mutate({ brandId, categoryId })
          }
          onReject={() => brandRejectMut.mutate()}
        />
      ) : null}

      {/* Spec §5.2 v1.20: orphan-transfer history hint. Visible only when
          history says this fingerprint has been a transfer ≥3 times with ≥80%
          consistency. Confirm = create the transfer pair (mirror on closed
          target works since spec §13 keeps closed accounts addressable). */}
      {nd.suggested_target_account_id != null ? (
        <OrphanTransferHint
          hint={{
            suggestedTargetAccountId: Number(nd.suggested_target_account_id),
            suggestedTargetAccountName: String(nd.suggested_target_account_name ?? ''),
            suggestedTargetIsClosed: Boolean(nd.suggested_target_is_closed),
            suggestedReason: String(nd.suggested_reason ?? ''),
          }}
          isPending={patchMut.isPending}
          onConfirm={() => {
            patchMut.mutate({
              action: 'confirm',
              operation_type: 'transfer',
              target_account_id: Number(nd.suggested_target_account_id),
            });
          }}
          onReject={() => {
            // Demote to regular; the editor clears suggested_* fields per spec §5.2.
            patchMut.mutate({
              action: 'confirm',
              operation_type: 'regular',
            });
          }}
        />
      ) : null}

      {/* Bottom row: type-aware fields + traffic light */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <CreatableSelect
          value={type}
          options={TYPE_OPTIONS}
          onChange={(v) => {
            setType(v as MainType);
            // Reset cross-type fields so we never send stale ids.
            setCategoryId(null);
            setCounterpartyId(null);
            setDebtPartnerId(null);
            setTransferAccountId(null);
            setDebtDirection('');
            setCreditKind('');
            setCreditAccountId(null);
            setCreditPrincipal('');
            setCreditInterest('');
          }}
          width={170}
          accentDot={txTypeOption.toneDot}
        />

        {type === 'debt' ? (
          <>
            <CreatableSelect
              value={debtDirection}
              options={debtDirOptionsFor(direction)}
              placeholder="— направление —"
              onChange={(v) => setDebtDirection(v as DebtDirection)}
              width={200}
            />
            <DebtPartnerSelect
              value={debtPartnerId}
              options={options.debtPartners}
              onChange={setDebtPartnerId}
              width={210}
            />
          </>
        ) : type === 'transfer' ? (
          <AccountSelect
            value={transferAccountId}
            options={options.accounts}
            onChange={setTransferAccountId}
            placeholder="— на свой счёт —"
            width={220}
          />
        ) : type === 'investment' ? (
          <InvestmentDirBadge direction={direction} />
        ) : type === 'credit_operation' ? (
          <>
            <CreatableSelect
              value={creditKind}
              options={CREDIT_KIND_OPTIONS}
              onChange={(v) => setCreditKind(v as CreditKind)}
              placeholder="— направление кредита —"
              width={210}
            />
            <CreatableSelect
              value={creditAccountId != null ? String(creditAccountId) : null}
              options={filteredCreditAccountOptions}
              onChange={(v) => setCreditAccountId(Number(v))}
              placeholder="— кредитный счёт —"
              width={220}
              emptyHint="Нет кредитных счетов"
            />
          </>
        ) : (
          // regular OR refund — both show category select; refund forces 'expense'
          <CategorySelect
            value={categoryId}
            options={filteredCategoryOptions}
            onChange={setCategoryId}
            kind={type === 'refund' ? 'expense' : (isIncome ? 'income' : 'expense')}
            width={210}
          />
        )}

        <div className="ml-auto flex items-center gap-1.5">
          <CounterpartyRazvorotButton
            value={counterpartyId}
            options={options.counterparties}
            onChange={(id) => { setCounterpartyId(id); attachMut.mutate(id); }}
            disabled={cpDisabled}
            compact
          />

          <button
            type="button"
            onClick={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              onEditDeep({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
            }}
            className="grid size-8 place-items-center rounded-md text-ink-3 transition hover:bg-bg-surface2 hover:text-ink"
            title="Подробное редактирование"
          >
            <Pencil className="size-3.5" />
          </button>
          <button
            type="button"
            className="grid size-8 place-items-center rounded-md text-ink-3 transition hover:bg-bg-surface2 hover:text-ink"
            title="Разделить транзакцию"
            onClick={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              onSplitOpen({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
            }}
          >
            <Split className="size-3.5" />
          </button>

          <span className="mx-1 inline-block h-5 w-px bg-line" />

          <TrafficBtn
            kind="excl"
            onClick={() => { triggerFly('excl'); exclMut.mutate(); }}
            title="Исключить из импорта"
          />
          <TrafficBtn
            kind="snooze"
            onClick={() => { triggerFly('snz'); parkMut.mutate(); }}
            title="Отложить на потом"
          />
          <TrafficBtn
            kind="apply"
            onClick={handleConfirm}
            title="Подтвердить"
            active={!patchMut.isPending && row.status === 'ready'}
          />
        </div>
      </div>

      {/* Optional second row: principal / interest for credit payment */}
      {type === 'credit_operation' && (creditKind === 'payment' || creditKind === 'early_repayment') ? (
        <CreditPaymentDetail
          totalAmount={Number(amount) || 0}
          principal={creditPrincipal}
          interest={creditInterest}
          onPrincipalChange={setCreditPrincipal}
          onInterestChange={setCreditInterest}
        />
      ) : null}
    </article>
  );
}

function Banner({ tone, children }: { tone: 'blue' | 'amber'; children: ReactNode }) {
  const cls =
    tone === 'blue'
      ? 'bg-accent-blue-soft text-accent-blue'
      : 'bg-accent-amber-soft text-accent-amber';
  return (
    <div className={`mt-2.5 flex items-center gap-2 rounded-lg ${cls} px-2.5 py-1.5 text-[11.5px]`}>
      <span className="select-none">·</span>
      <span className="flex-1 leading-snug">{children}</span>
    </div>
  );
}

function InvestmentDirBadge({ direction }: { direction: 'income' | 'expense' | string }) {
  const v = investmentDirFor(direction);
  const o = INVEST_DIR_OPTIONS.find((x) => x.value === v) ?? INVEST_DIR_OPTIONS[0];
  return (
    <span
      title="Направление определяется автоматически по знаку операции"
      className="inline-flex h-8 items-center gap-2 rounded-lg border border-dashed border-line-strong bg-bg-surface2 px-3 text-xs text-ink-2"
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
    <div className="mt-3 grid grid-cols-[1fr_1fr_auto] items-end gap-3 rounded-xl border border-line bg-bg-surface2 p-3">
      <label className="block">
        <div className="mb-1 text-[10.5px] text-ink-3">Основной долг</div>
        <input
          type="number"
          step="0.01"
          inputMode="decimal"
          value={principal}
          onChange={(e) => onPrincipalChange(e.target.value)}
          placeholder="0.00"
          className="block h-7 w-full rounded-md border border-line bg-bg-surface px-2.5 text-right font-mono text-xs outline-none focus:border-line-strong"
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
          className="block h-7 w-full rounded-md border border-line bg-bg-surface px-2.5 text-right font-mono text-xs outline-none focus:border-line-strong"
        />
      </label>
      <div className="min-w-[180px] text-[11px] leading-tight">
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
