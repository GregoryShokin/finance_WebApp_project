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

import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
} from '@/components/import/entity-selects';
// CounterpartyRazvorotButton removed in v1.24 — Brand-Counterparty UI
// unification (Option B). Brand picker is the sole entry point.
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
  confirmRowBrand,
  excludeImportRow,
  parkImportRow,
  rejectRowBrand,
  updateImportRow,
} from '@/lib/api/imports';
import { BrandPrompt } from './brand-prompt';
import { BrandCategoryEdit } from './brand-category-edit';
import { BrandEditModal } from './brand-edit-modal';
import { NameBindModal } from './name-bind-modal';
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
  /** Legacy single-session prop. Queue mode (v1.23) prefers
   * `row.session_id` (each row carries its own session); the prop is the
   * fallback for legacy single-session preview payloads. */
  sessionId: number;
  options: TxRowOptions;
  onEditDeep: (origin: { x: number; y: number }) => void;
  onSplitOpen: (origin: { x: number; y: number }) => void;
}) {
  // Per-row session — queue payload stamps `row.session_id` so per-row
  // API calls route to the correct session even when the parent renders
  // many rows from many sessions.
  const effectiveSessionId = row.session_id ?? sessionId;
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
  // Phase C dual-write: track nd.brand_id alongside nd.counterparty_id so
  // payload submission keeps both stores in sync. The row UI doesn't pick
  // a brand directly — value comes from the resolver / brand-confirm path
  // and we just preserve it on save.
  const [brandId, setBrandId]                     = useState<number | null>((nd.brand_id as number | null) ?? null);
  const [debtPartnerId, setDebtPartnerId]         = useState<number | null>((nd.debt_partner_id as number | null) ?? null);
  const [debtDirection, setDebtDirection]         = useState<DebtDirection | ''>(((nd.debt_direction as DebtDirection) || ''));
  const [transferAccountId, setTransferAccountId] = useState<number | null>((nd.target_account_id as number | null) ?? null);
  const [creditKind, setCreditKind]               = useState<CreditKind | ''>(operationTypeToCreditKind((nd.operation_type as string | undefined) ?? undefined));
  const [creditAccountId, setCreditAccountId]     = useState<number | null>((nd.credit_account_id as number | null) ?? null);
  const [creditPrincipal, setCreditPrincipal]     = useState<string>(((nd.credit_principal_amount as string | number | null) ?? '').toString());
  const [creditInterest, setCreditInterest]       = useState<string>(((nd.credit_interest_amount as string | number | null) ?? '').toString());
  // v1.27 unified «+ Имя / Бренд» modal. Replaces the prior split between
  // a Brand picker (BrandPickerModal) and the inline DebtPartnerSelect
  // pick-or-create flow — one button on the row, one modal that routes
  // to Brand or DebtPartner via a single `bind-name` endpoint.
  const [nameBindOpen, setNameBindOpen]           = useState(false);
  // Ph8b: «Изменить бренд» — only available on confirmed rows; modal
  // gates write actions on `is_global=false` (global brands are read-only).
  const [brandEditOpen, setBrandEditOpen]         = useState(false);

  // External refresh sync: when an out-of-band update lands on the row's
  // normalized_data (e.g. brand confirm propagation, apply-brand-category
  // sweep, suggested-brand bulk-confirm), `nd.category_id` / `counterparty_id`
  // change but the local state stays at whatever the user last picked. This
  // makes "Применить ко всем" look like it didn't apply when in fact the DB
  // is correct — the inputs simply hadn't reread the prop. Sync on prop
  // change; user's mid-edit state survives because changes propagate via
  // setCategoryId/setCounterpartyId (state would already match prop).
  const externalCategoryId = (nd.category_id as number | null) ?? null;
  const externalCounterpartyId = (nd.counterparty_id as number | null) ?? null;
  const externalBrandId = (nd.brand_id as number | null) ?? null;
  // v1.27 — sync debt_partner_id from normalized_data so a contact bind
  // (which stamps nd.debt_partner_id on debt rows) is reflected in the
  // local state used by handleConfirm. Without this, the row picks up the
  // new partner but the confirm payload still carries the old (possibly
  // null) value because state hasn't reread the prop.
  const externalDebtPartnerId = (nd.debt_partner_id as number | null) ?? null;
  useEffect(() => {
    setCategoryId(externalCategoryId);
  }, [externalCategoryId]);
  useEffect(() => {
    setCounterpartyId(externalCounterpartyId);
  }, [externalCounterpartyId]);
  useEffect(() => {
    setBrandId(externalBrandId);
  }, [externalBrandId]);
  useEffect(() => {
    setDebtPartnerId(externalDebtPartnerId);
  }, [externalDebtPartnerId]);

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
  // v1.27 — bound personal contact (DebtPartner via «+ Имя / Бренд»). Same
  // override semantics as confirmedBrandName: when present, the contact name
  // is the primary label and the raw bank description moves to the subtitle.
  // Backend exposes the resolution via `row.personal_counterparty_*` fields
  // (covers both same-row stamps and cross-session identifier lookups), so
  // we don't need to peek into normalized_data here.
  const personalContactId = (row.personal_counterparty_id as number | null) ?? null;
  const personalContactName = (row.personal_counterparty_name as string | null) ?? null;
  const personalContactCategoryId = (row.personal_counterparty_category_id as number | null) ?? null;
  const description = confirmedBrandName || personalContactName || rawDescription;
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

  // attachMut (CounterpartyFingerprint quick-binding) removed in v1.24 —
  // brand-picker handles binding through brand-confirm path.

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
      payload.brand_id = null;
      payload.category_id = null;
      if (debtDirection) payload.debt_direction = debtDirection;
    } else if (type === 'transfer') {
      payload.operation_type = 'transfer';
      payload.target_account_id = transferAccountId;
      payload.counterparty_id = null;
      payload.brand_id = null;
      payload.category_id = null;
    } else if (type === 'investment') {
      payload.operation_type = investmentDirToOperationType(investmentDirFor(direction));
      payload.counterparty_id = null;
      payload.brand_id = null;
      payload.category_id = null;
    } else if (type === 'credit_operation') {
      payload.operation_type = creditKind ? creditKindToOperationType(creditKind) : 'regular';
      payload.credit_account_id = creditAccountId;
      payload.counterparty_id = null;
      payload.brand_id = null;
      payload.category_id = null;
      if (creditKind === 'payment' || creditKind === 'early_repayment') {
        payload.credit_principal_amount = creditPrincipal ? Number(creditPrincipal) : null;
        payload.credit_interest_amount  = creditInterest  ? Number(creditInterest)  : null;
      }
    } else if (type === 'refund') {
      payload.operation_type = 'refund';
      payload.category_id = categoryId;
      payload.counterparty_id = counterpartyId;
      payload.brand_id = brandId;
    } else {
      payload.operation_type = 'regular';
      payload.category_id = categoryId;
      payload.counterparty_id = counterpartyId;
      payload.brand_id = brandId;
    }
    patchMut.mutate(payload);
  };

  const txTypeOption = TYPE_OPTIONS.find((t) => t.value === type) ?? TYPE_OPTIONS[0];
  const cpDisabled = type === 'debt' || type === 'transfer' || type === 'investment' || type === 'credit_operation';

  // Source pill (queue mode v1.23) — compact bank+account label so the
  // user knows which statement this row came from in the unified list.
  // Hidden in legacy single-session view (row.account_name undefined).
  const sourcePill = row.account_name ? (
    <span
      title={`${row.bank_code ?? ''} · ${row.account_name}`}
      className="inline-flex max-w-[160px] items-center gap-1 truncate rounded-md border border-line bg-bg-surface2 px-1.5 py-0.5 text-[10px] font-medium text-ink-3"
    >
      {row.bank_code ? `${row.bank_code} · ` : ''}{row.account_name}
    </span>
  ) : null;

  // Read-only transfer rendering (v1.23). Transfer rows now appear inline
  // in the chronological list as informational entries — already paired
  // by the matcher (or stamped as transfer with target by bank-mechanics),
  // so the user can't edit them here. Orphan transfers (operation_type
  // ='transfer' without transfer_match AND without target_account_id) fall
  // through to the full row UI so the user can still resolve them.
  const tmInfo = nd.transfer_match as
    | { kind?: string; partner_account_name?: string | null; partner_account_id?: number | null }
    | undefined;
  const targetAccountName = (() => {
    if (tmInfo?.partner_account_name) return String(tmInfo.partner_account_name);
    const tid = nd.target_account_id as number | null | undefined;
    if (tid != null) {
      return options.accountsRaw?.find((a) => a.id === tid)?.name ?? null;
    }
    return null;
  })();
  const isTransferReadOnly =
    !!tmInfo
    || (nd.operation_type === 'transfer' && targetAccountName !== null);
  if (isTransferReadOnly) {
    const arrow = isIncome ? '←' : '→';
    return (
      <article
        ref={rowScope}
        className="border-t border-line bg-bg-surface2/40 px-4 py-2.5 first:border-t-0 lg:px-5"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <div className="mt-0.5 flex shrink-0 flex-col items-start gap-1">
              <span className="font-mono text-[11px] text-ink-3">{fmtDateTime(date)}</span>
              {sourcePill}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 text-[12px] font-medium text-ink">
                <span className="rounded-md bg-bg-surface px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-3">
                  Перевод
                </span>
                {targetAccountName ? (
                  <span className="text-ink-2">
                    {arrow} {targetAccountName}
                  </span>
                ) : null}
              </div>
              {description ? (
                <div className="mt-0.5 text-[11px] text-ink-3 break-words">
                  {description}
                </div>
              ) : null}
            </div>
          </div>
          <div className="shrink-0 text-right text-[13px] font-medium text-ink">
            {fmtRubSigned(amount, isIncome ? 'income' : 'expense')}
          </div>
        </div>
      </article>
    );
  }

  return (
    <article ref={rowScope} className="border-t border-line bg-bg-surface px-4 py-3.5 first:border-t-0 lg:px-5">
      {/* Top row: date + merchant + amount + status */}
      <div className="flex items-start justify-between gap-2.5">
        <div className="flex min-w-0 items-start gap-3">
          <div className="mt-0.5 flex shrink-0 flex-col items-start gap-1">
            <span className="font-mono text-[11px] text-ink-3">{fmtDateTime(date)}</span>
            {sourcePill}
          </div>
          <div className="min-w-0">
            <div className="text-[13px] font-medium text-ink">
              <span className="break-words">{description || '(без описания)'}</span>
              {cardLast4 ? (
                <span className="font-normal text-ink-3"> · карта {cardLast4}</span>
              ) : null}
            </div>
            {(confirmedBrandName || personalContactName) && rawDescription
              && rawDescription !== (confirmedBrandName || personalContactName) ? (
              <div className="mt-0.5 text-[11px] text-ink-3 break-words">
                {rawDescription}
              </div>
            ) : null}
            {confirmedBrandName ? (
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <BrandCategoryEdit
                  brandId={Number(nd.user_confirmed_brand_id)}
                  brandName={confirmedBrandName}
                  currentCategoryId={(nd.category_id as number | null) ?? null}
                  categories={filteredCategoryOptions}
                />
                <button
                  type="button"
                  onClick={() => setBrandEditOpen(true)}
                  title={`Редактировать бренд «${confirmedBrandName}»`}
                  className="inline-flex items-center gap-1 rounded-md border border-line bg-bg-surface px-2 py-0.5 text-[11px] text-ink-3 hover:border-ink-3 hover:bg-bg-surface2 hover:text-ink"
                >
                  <Pencil className="size-3" /> Изменить бренд
                </button>
              </div>
            ) : personalContactName ? (
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => setNameBindOpen(true)}
                  title={`Изменить контакт «${personalContactName}»`}
                  className="inline-flex items-center gap-1 rounded-md border border-line bg-bg-surface px-2 py-0.5 text-[11px] text-ink hover:border-ink-3 hover:bg-bg-surface2"
                >
                  {personalContactName}
                </button>
                {personalContactCategoryId != null ? (
                  <span className="inline-flex items-center rounded-md border border-line bg-bg-surface2 px-2 py-0.5 text-[11px] text-ink-3">
                    {(row.personal_counterparty_category_name as string | null) ?? ''}
                  </span>
                ) : null}
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
          propagates to same-brand siblings server-side; reject is local.
          spec v1.26 / Brand Registry §17 — defensive: even though the
          resolver no longer returns a match for personal-identifier rows,
          legacy rows imported before v1.26 may still carry a stale
          brand_id. Hide the prompt so the user can't bind a phone/contract
          to a brand by clicking «Да». */}
      {nd.brand_id != null
        && nd.user_confirmed_brand_id == null
        && nd.user_rejected_brand_id == null
        && (type === 'regular' || type === 'refund')
        && !row.is_personal_identifier ? (
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

      {/* spec v1.27 — unified «+ Имя / Бренд» entry point. Visible on
          regular / refund / debt / credit_operation rows that don't
          already carry a brand or contact stamp. Transfer rows are
          excluded (transfer between own accounts has no counterparty —
          §6.10 / §12.11). Debt rows lock the modal's kind to «контакт»
          per §12.2 (operation_type='debt' requires debt_partner_id and
          forbids brand_id). */}
      {type !== 'transfer'
        && type !== 'investment'
        && nd.user_confirmed_brand_id == null
        && personalContactId == null
        && (type !== 'debt' || debtPartnerId == null) ? (
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setNameBindOpen(true)}
            className="inline-flex items-center gap-1 rounded-md border border-line bg-bg-surface px-2 py-0.5 text-[11px] text-ink-3 hover:border-ink-3 hover:bg-bg-surface2 hover:text-ink"
          >
            + Имя / Бренд
          </button>
        </div>
      ) : null}

      {nameBindOpen ? (
        <NameBindModal
          open={nameBindOpen}
          rowId={row.id}
          rawDescription={rawDescription}
          categoryOptions={filteredCategoryOptions}
          defaultKind={
            type === 'debt'
              ? 'contact'
              : (row.is_personal_identifier ? 'contact' : 'brand')
          }
          lockedKind={type === 'debt' ? 'contact' : null}
          onClose={() => setNameBindOpen(false)}
          onSuccess={(resp) => {
            // Mirror local debt_partner_id state so handleConfirm sends
            // the right FK. Brand binding is reflected via nd refresh
            // (preview invalidation pulls the new normalized_data).
            if (resp.kind === 'contact' && type === 'debt') {
              setDebtPartnerId(resp.id);
            }
          }}
        />
      ) : null}

      {brandEditOpen && nd.user_confirmed_brand_id != null ? (
        <BrandEditModal
          open={brandEditOpen}
          brandId={Number(nd.user_confirmed_brand_id)}
          onClose={() => setBrandEditOpen(false)}
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
            setBrandId(null);
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
          // v1.27 — partner picking moved into the unified «+ Имя / Бренд»
          // modal (locked to kind='contact' on debt rows). The inline
          // DebtPartnerSelect was the second entry point that this PR
          // collapsed; the row still picks debt direction here, but the
          // partner is named via the same single button as every other
          // row type.
          <CreatableSelect
            value={debtDirection}
            options={debtDirOptionsFor(direction)}
            placeholder="— направление —"
            onChange={(v) => setDebtDirection(v as DebtDirection)}
            width={200}
          />
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
          {/* v1.24 Brand-Counterparty unification: the 👤 quick-pick was a
              parallel entry that wrote nd.counterparty_id without going
              through Brand. Removed — «Выбрать бренд» pill above (brand
              picker) is the sole entry point and creates Brand →
              Counterparty in one step via confirm_brand_for_row. */}

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
