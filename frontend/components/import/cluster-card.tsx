'use client';

/**
 * Bulk-cluster review card (И-08 Этап 3).
 *
 * Renders one fingerprint or brand cluster with:
 *   - collapsed header: brand/skeleton + count + total amount + suggested
 *     category + "Подтвердить всё" button
 *   - expanded body: virtualized row list with per-row checkbox (include/
 *     exclude from the batch) and inline category override
 *
 * Bulk-action panel on top applies one category + one operation_type across
 * all still-checked rows. Sticky edits (rows the user modified individually)
 * are not overwritten by subsequent bulk-apply clicks.
 *
 * Contract with backend: `POST /imports/{id}/clusters/bulk-apply` expects a
 * flat list of per-row updates, so this component never sends "one category
 * for all" — it expands the UI choice into N explicit row updates before
 * hitting the API.
 */

import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Pencil, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { CollapsibleChevron } from '@/components/ui/collapsible';
import { SearchSelect, type SearchSelectItem } from '@/components/ui/search-select';
import { ExpandableCard } from '@/components/dashboard-new/expandable-card';
import { AttachToCounterpartyButton } from '@/components/import/attach-counterparty';
import { CategoryDialog } from '@/components/categories/category-dialog';
import { DebtPartnerDialog } from '@/components/debt-partners/debt-partner-dialog';
import { attachRowToCounterparty, bulkApplyCluster, detachImportRowFromCluster } from '@/lib/api/imports';
import { createCategory } from '@/lib/api/categories';
import { createCounterparty, getCounterparties } from '@/lib/api/counterparties';
import { createDebtPartner, getDebtPartners } from '@/lib/api/debt-partners';
import { getAccounts } from '@/lib/api/accounts';
import type { Account } from '@/types/account';
import type {
  BulkApplyPayload,
  BulkClusterRowUpdate,
  BulkClustersResponse,
  BulkFingerprintCluster,
  ImportPreviewRow,
} from '@/types/import';
import type { Category, CreateCategoryPayload } from '@/types/category';
import type { Counterparty } from '@/types/counterparty';
import type { DebtPartner, CreateDebtPartnerPayload } from '@/types/debt-partner';

export type ClusterCardMeta =
  | {
      kind: 'fingerprint';
      cluster: BulkFingerprintCluster;
    }
  | {
      kind: 'brand';
      brand: string;
      direction: string;
      count: number;
      totalAmount: string;
      members: BulkFingerprintCluster[];
    }
  | {
      // Phase 3 — counterparty-centric grouping.
      kind: 'counterparty';
      counterpartyId: number;
      counterpartyName: string;
      direction: string;
      count: number;
      totalAmount: string;
      members: BulkFingerprintCluster[];
    };

type Props = {
  meta: ClusterCardMeta;
  sessionId: number;
  rowsById: Map<number, ImportPreviewRow>;
  categories: Category[];
  bulkClusters?: BulkClustersResponse;
  onApplied: () => void;
};

// Per-row client state — picked category/counterparty, include/exclude, and
// operation-type override (default 'regular', but the user can switch any
// row inside a cluster to a completely different kind: transfer, debt,
// refund, credit operation, investment). Sub-fields carry the data each
// operation type needs.
// Keyed by row.id so toggling "expand brand" doesn't reset selections.
// `edited` flags point out which fields were set manually (so bulk-apply
// doesn't overwrite them).
type RowOperationType = 'regular' | 'transfer' | 'debt' | 'refund' | 'investment' | 'credit_operation';
type RowDebtDirection = 'borrowed' | 'lent' | 'repaid' | 'collected';
type RowInvestDir = 'buy' | 'sell';
type RowCreditKind = 'disbursement' | 'payment' | 'early_repayment';

type RowState = {
  categoryId: number | null;
  counterpartyId: number | null;
  debtPartnerId: number | null;
  included: boolean;
  categoryEdited: boolean;
  counterpartyEdited: boolean;
  debtPartnerEdited: boolean;
  operationType: RowOperationType;
  operationTypeEdited: boolean;
  targetAccountId: number | null;
  debtDirection: RowDebtDirection;
  investDir: RowInvestDir;
  creditKind: RowCreditKind;
  creditAccountId: number | null;
  creditPrincipal: string;
  creditInterest: string;
};

// regular, refund rows sum into categorized spending; debt rows reference
// a DebtPartner instead of a Category (см. CLAUDE.md § Counterparty vs
// DebtPartner и backend TransactionService._validate_payload — для debt
// counterparty_id запрещён, нужен debt_partner_id). Transfer / investment /
// credit_operation — внутренние перемещения или инструменты, категория им
// тоже не нужна.
function rowNeedsCategory(op: RowOperationType): boolean {
  return op === 'regular' || op === 'refund';
}

function formatMoney(value: string | number): string {
  const n = typeof value === 'string' ? Number(value) : value;
  if (!Number.isFinite(n)) return String(value);
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'RUB',
    maximumFractionDigits: 0,
  }).format(Math.abs(n));
}

function ClusterCardImpl({ meta, sessionId, rowsById, categories, bulkClusters, onApplied }: Props) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [bulkCategoryId, setBulkCategoryId] = useState<number | null>(() => {
    if (meta.kind === 'fingerprint') return meta.cluster.candidate_category_id;
    // Brand and counterparty clusters inherit the category from their first
    // member that has an active rule. Without this, single-word brands
    // ("Pyaterochka", "Magnit") and counterparties always open with empty
    // category even though per-fingerprint members already know the answer.
    for (const m of meta.members) {
      if (m.candidate_category_id != null) return m.candidate_category_id;
    }
    return null;
  });
  const [bulkQuery, setBulkQuery] = useState(() => {
    const initialCatId = meta.kind === 'fingerprint'
      ? meta.cluster.candidate_category_id
      : (meta.members.find((m) => m.candidate_category_id != null)?.candidate_category_id ?? null);
    if (initialCatId == null) return '';
    return categories.find((c) => c.id === initialCatId)?.name ?? '';
  });
  // Counterparty kind prefills the counterparty picker with its own id/name.
  const [bulkCounterpartyId, setBulkCounterpartyId] = useState<number | null>(
    meta.kind === 'counterparty' ? meta.counterpartyId : null,
  );
  const [bulkCounterpartyQuery, setBulkCounterpartyQuery] = useState(
    meta.kind === 'counterparty' ? meta.counterpartyName : '',
  );
  const [rowState, setRowState] = useState<Record<number, RowState>>({});
  const counterpartiesQuery = useQuery({
    queryKey: ['counterparties'],
    queryFn: getCounterparties,
  });
  const counterparties: Counterparty[] = counterpartiesQuery.data ?? [];
  const debtPartnersQuery = useQuery({
    queryKey: ['debt-partners'],
    queryFn: getDebtPartners,
  });
  const debtPartners: DebtPartner[] = debtPartnersQuery.data ?? [];

  // Accounts are needed for per-row transfer/credit sub-pickers inside the
  // inline row editor. We fetch once for the whole card — same cache as
  // import-moderation-panel, so no extra network cost.
  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: () => getAccounts(),
  });
  const accounts: Account[] = accountsQuery.data ?? [];
  const creditAccounts = useMemo(
    () => accounts.filter((a) => a.is_credit || a.account_type === 'credit' || a.account_type === 'credit_card' || a.account_type === 'installment_card'),
    [accounts],
  );
  const transferAccounts = useMemo(
    () => [...accounts].sort((a, b) => a.name.localeCompare(b.name, 'ru')),
    [accounts],
  );
  const counterpartyById = useMemo(() => {
    const map = new Map<number, Counterparty>();
    for (const cp of counterparties) map.set(cp.id, cp);
    return map;
  }, [counterparties]);

  const createCounterpartyMutation = useMutation({
    mutationFn: (name: string) => createCounterparty({ name }),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ['counterparties'] });
      setBulkCounterpartyId(created.id);
      setBulkCounterpartyQuery(created.name);
      toast.success(`Контрагент «${created.name}» создан`);
    },
    onError: (err: Error) => toast.error(err.message || 'Не удалось создать контрагента'),
  });

  // Aggregate rows across members (brand/counterparty) or use the single
  // cluster's ids.
  const allRowIds = useMemo<number[]>(() => {
    if (meta.kind === 'fingerprint') return meta.cluster.row_ids;
    return meta.members.flatMap((m) => m.row_ids);
  }, [meta]);

  const rows = useMemo<ImportPreviewRow[]>(
    () => allRowIds.map((id) => rowsById.get(id)).filter((r): r is ImportPreviewRow => !!r),
    [allRowIds, rowsById],
  );

  // Only show categories compatible with the cluster direction.
  // Refund clusters are income by direction but must pick from expense-kind
  // categories (the refund compensates an expense in that category), so we
  // override the filter when `is_refund` is true.
  const metaDirection = meta.kind === 'fingerprint' ? meta.cluster.direction : meta.direction;
  const metaIsRefund = meta.kind === 'fingerprint' && Boolean(meta.cluster.is_refund);
  const filteredCategories = useMemo<Category[]>(() => {
    const wanted = metaIsRefund
      ? 'expense'
      : metaDirection === 'income'
        ? 'income'
        : 'expense';
    return categories.filter((c) => c.kind === wanted);
  }, [categories, metaDirection, metaIsRefund]);

  const categoryItems = useMemo<SearchSelectItem[]>(
    () => filteredCategories.map((c) => ({ value: String(c.id), label: c.name })),
    [filteredCategories],
  );

  const categoryById = useMemo(() => {
    const map = new Map<number, Category>();
    for (const c of categories) map.set(c.id, c);
    return map;
  }, [categories]);

  // Title + subtitle for the collapsed header.
  // Transfer-like fingerprint clusters carry a concrete identifier (phone /
  // contract / card / iban) — prefer that over the masked skeleton so users
  // see "Перевод по номеру телефона +79…6612" instead of "… <PHONE>".
  const title = (() => {
    if (meta.kind === 'counterparty') return meta.counterpartyName;
    if (meta.kind === 'brand') return meta.brand.charAt(0).toUpperCase() + meta.brand.slice(1);
    return meta.cluster.identifier_value
      ? headerFromIdentifier(
          meta.cluster.identifier_key ?? null,
          meta.cluster.identifier_value,
          meta.cluster.skeleton,
        )
      : headerFromSkeleton(meta.cluster.skeleton);
  })();
  const count = meta.kind === 'fingerprint' ? meta.cluster.count : meta.count;
  const totalAmount = meta.kind === 'fingerprint' ? String(meta.cluster.total_amount) : meta.totalAmount;
  const direction = metaDirection;
  const subtitle = `${count} операц${count === 1 ? 'ия' : count < 5 ? 'ии' : 'ий'} · ${formatMoney(totalAmount)}`;

  function defaultRowState(row?: ImportPreviewRow): RowState {
    // Derive initial values from the row's normalized_data when available —
    // it's the strongest signal because backend writes user edits there
    // (after Apply / bulk-apply / commit). Falling back to bulk-default
    // only when the row has nothing of its own. Without this, F5 or any
    // unmount/mount cycle re-renders rows with the cluster-level default,
    // visually rolling back per-row edits — and any subsequent action then
    // submits stale state back, overwriting the correct DB row.
    const nd = (row?.normalized_data ?? {}) as Record<string, unknown>;
    const rowOp = String(nd.operation_type ?? '').toLowerCase();
    const rowIsRefund = Boolean(nd.is_refund);
    let initialOp: RowOperationType = 'regular';
    if (rowOp === 'refund' || rowIsRefund) initialOp = 'refund';
    else if (rowOp === 'transfer') initialOp = 'transfer';
    else if (rowOp === 'debt') initialOp = 'debt';
    else if (rowOp === 'investment_buy' || rowOp === 'investment_sell') initialOp = 'investment';
    else if (rowOp === 'credit_disbursement' || rowOp === 'credit_payment' || rowOp === 'credit_early_repayment') initialOp = 'credit_operation';
    const initialInvestDir: RowInvestDir = rowOp === 'investment_sell' ? 'sell' : 'buy';
    const initialCreditKind: RowCreditKind =
      rowOp === 'credit_payment' ? 'payment' :
      rowOp === 'credit_early_repayment' ? 'early_repayment' : 'disbursement';
    const persistedCategoryId = nd.category_id != null ? Number(nd.category_id) : null;
    const persistedCounterpartyId = nd.counterparty_id != null ? Number(nd.counterparty_id) : null;
    const persistedDebtDirection = (() => {
      const v = String(nd.debt_direction ?? '').toLowerCase();
      return v === 'lent' || v === 'borrowed' || v === 'repaid' || v === 'collected'
        ? (v as RowDebtDirection)
        : 'borrowed';
    })();
    const persistedPrincipal = nd.principal_amount != null ? String(nd.principal_amount) : '';
    const persistedInterest = nd.interest_amount != null ? String(nd.interest_amount) : '';
    return {
      categoryId: persistedCategoryId ?? bulkCategoryId,
      counterpartyId: persistedCounterpartyId ?? bulkCounterpartyId,
      debtPartnerId: nd.debt_partner_id ? Number(nd.debt_partner_id) : null,
      included: true,
      categoryEdited: false,
      counterpartyEdited: false,
      debtPartnerEdited: false,
      operationType: initialOp,
      operationTypeEdited: false,
      targetAccountId: nd.target_account_id ? Number(nd.target_account_id) : null,
      debtDirection: persistedDebtDirection,
      investDir: initialInvestDir,
      creditKind: initialCreditKind,
      creditAccountId: nd.credit_account_id ? Number(nd.credit_account_id) : null,
      creditPrincipal: persistedPrincipal,
      creditInterest: persistedInterest,
    };
  }

  function getRowState(rowId: number): RowState {
    return rowState[rowId] ?? defaultRowState(rowsById.get(rowId));
  }

  function updateRowState(rowId: number, patch: Partial<RowState>) {
    setRowState((prev) => {
      const current = prev[rowId] ?? defaultRowState(rowsById.get(rowId));
      return { ...prev, [rowId]: { ...current, ...patch } };
    });
  }

  const detachMutation = useMutation({
    mutationFn: (rowId: number) => detachImportRowFromCluster(rowId),
    onSuccess: async () => {
      // Refetch clusters + preview: the detached row leaves this cluster and
      // lands standalone in the inline "Требуют твоего внимания" list.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['imports', sessionId, 'bulk-clusters'] }),
        queryClient.invalidateQueries({ queryKey: ['imports', sessionId, 'preview'] }),
        queryClient.invalidateQueries({ queryKey: ['imports', sessionId, 'moderation-status'] }),
      ]);
    },
    onError: (err: Error) => toast.error(err.message || 'Не удалось открепить строку'),
  });

  function toggleRowIncluded(rowId: number) {
    // Unchecking a row actually *detaches* it from this cluster server-side —
    // it moves to the inline attention bucket for individual review. We don't
    // support re-attaching from here: once detached, the row is no longer in
    // the cluster's row list on the next render, so the checkbox disappears.
    detachMutation.mutate(rowId);
  }

  function setRowCategory(rowId: number, categoryId: number | null) {
    updateRowState(rowId, { categoryId, categoryEdited: true });
  }

  function setRowDebtPartner(rowId: number, debtPartnerId: number | null) {
    updateRowState(rowId, { debtPartnerId, debtPartnerEdited: true });
  }

  // rowNeedsCategory is also used in ClusterRowList so it lives at module level.

  function applyBulkToAllIncluded() {
    if (bulkCategoryId == null && bulkCounterpartyId == null) {
      toast.error('Выбери категорию или контрагента для массового применения');
      return;
    }
    let appliedCount = 0;
    let typeFlippedCount = 0;
    setRowState((prev) => {
      const next: Record<number, RowState> = { ...prev };
      for (const row of rows) {
        const current = next[row.id] ?? defaultRowState(row);
        if (!current.included) continue;

        // Picking a bulk category means "these rows all belong in this
        // category" — which only makes sense for category-using types
        // (regular / refund / debt). If the system pre-classified some
        // rows as transfer/investment/credit (common false positive: 19
        // "Внутрибанковский перевод" rows that are actually salary), flip
        // them to 'regular' so the category can land. Rows the user
        // manually edited via the pencil icon keep their chosen type.
        let nextOp = current.operationType;
        if (
          bulkCategoryId != null
          && !rowNeedsCategory(nextOp)
          && !current.operationTypeEdited
        ) {
          nextOp = 'regular';
          typeFlippedCount += 1;
        }

        const opChanged = nextOp !== current.operationType;
        const shouldApplyCategory = rowNeedsCategory(nextOp);

        next[row.id] = {
          ...current,
          operationType: nextOp,
          // When flipping away from transfer/credit, clear the fields that
          // belonged to the previous type so stale IDs don't travel with
          // the commit payload.
          ...(opChanged
            ? { targetAccountId: null, creditAccountId: null }
            : {}),
          // sticky: don't overwrite fields the user already tweaked individually.
          // Clear category for rows whose (new) type doesn't use one.
          categoryId: shouldApplyCategory
            ? (current.categoryEdited ? current.categoryId : (bulkCategoryId ?? current.categoryId))
            : null,
          counterpartyId: current.counterpartyEdited
            ? current.counterpartyId
            : (bulkCounterpartyId ?? current.counterpartyId),
        };
        appliedCount += 1;
      }
      return next;
    });
    const plural = appliedCount === 1 ? 'строке' : appliedCount < 5 ? 'строкам' : 'строкам';
    if (typeFlippedCount > 0) {
      toast.success(`Применено к ${appliedCount} ${plural} (${typeFlippedCount} переключено на «Обычная»)`);
    } else {
      toast.success(`Применено к ${appliedCount} ${plural}`);
    }
  }

  // Per-row validation: can this row be sent as part of bulk-apply? Same
  // requirements as the attention-card "Apply" button (see canApply in
  // import-moderation-panel), just compressed here because the cluster-card
  // carries its own state shape.
  function rowIsReady(row: ImportPreviewRow, s: RowState): boolean {
    if (!s.included) return false;
    switch (s.operationType) {
      case 'regular':
      case 'refund':
        return s.categoryId != null;
      case 'debt':
        return s.debtPartnerId != null;
      case 'transfer':
        return s.targetAccountId != null;
      case 'credit_operation':
        if (s.creditAccountId == null) return false;
        if (s.creditKind === 'payment') {
          const p = parseFloat(s.creditPrincipal.replace(',', '.'));
          const i = parseFloat(s.creditInterest.replace(',', '.'));
          return Number.isFinite(p) && p >= 0 && Number.isFinite(i) && i >= 0;
        }
        return true;
      case 'investment':
        return true;
    }
  }

  // Translate the frontend's grouped operation type + sub-direction into
  // the backend's flat operation_type enum (investment_buy vs investment_sell,
  // credit_disbursement vs credit_payment vs credit_early_repayment).
  function resolveBackendOpType(s: RowState): string {
    if (s.operationType === 'investment') {
      return s.investDir === 'sell' ? 'investment_sell' : 'investment_buy';
    }
    if (s.operationType === 'credit_operation') {
      if (s.creditKind === 'payment') return 'credit_payment';
      if (s.creditKind === 'early_repayment') return 'credit_early_repayment';
      return 'credit_disbursement';
    }
    return s.operationType;
  }

  const applyMutation = useMutation({
    mutationFn: async () => {
      const updates: BulkClusterRowUpdate[] = [];
      for (const row of rows) {
        const s = getRowState(row.id);
        if (!rowIsReady(row, s)) continue;
        const update: BulkClusterRowUpdate = {
          row_id: row.id,
          operation_type: resolveBackendOpType(s),
          counterparty_id: s.counterpartyId,
        };
        // Only attach the fields the backend expects for this op_type.
        // Send nulls explicitly for fields that don't apply so backend
        // can clear any stale values from prior previews.
        if (rowNeedsCategory(s.operationType)) {
          update.category_id = s.categoryId;
        } else {
          update.category_id = null;
        }
        if (s.operationType === 'transfer') {
          update.target_account_id = s.targetAccountId;
        }
        if (s.operationType === 'debt') {
          update.debt_direction = s.debtDirection;
          // Backend invariant (TransactionService._validate_payload):
          // operation_type='debt' требует debt_partner_id, отвергает counterparty_id.
          update.debt_partner_id = s.debtPartnerId;
          update.counterparty_id = null;
        } else {
          // Любой не-debt operation_type отвергает debt_partner_id (тот же
          // инвариант). Отправляем явный null чтобы стереть прежние правки.
          update.debt_partner_id = null;
        }
        if (s.operationType === 'credit_operation') {
          update.credit_account_id = s.creditAccountId;
          if (s.creditKind === 'payment') {
            const p = parseFloat(s.creditPrincipal.replace(',', '.')) || 0;
            const i = parseFloat(s.creditInterest.replace(',', '.')) || 0;
            update.credit_principal_amount = String(p);
            update.credit_interest_amount = String(i);
          }
        }
        updates.push(update);
      }
      if (updates.length === 0) {
        throw new Error('Ни одной строки готовой к подтверждению');
      }
      const clusterKey = (() => {
        if (meta.kind === 'fingerprint') return meta.cluster.fingerprint;
        if (meta.kind === 'brand') return meta.brand;
        return `counterparty:${meta.counterpartyId}`;
      })();
      const payload: BulkApplyPayload = {
        cluster_key: clusterKey,
        cluster_type: meta.kind,
        updates,
      };
      return bulkApplyCluster(sessionId, payload);
    },
    onSuccess: async (data) => {
      const skipped = data.skipped_row_ids.length;
      if (skipped > 0) {
        toast.info(
          `Подтверждено ${data.confirmed_count}, пропущено ${skipped} (уже импортированы)`,
        );
      } else {
        toast.success(`Подтверждено ${data.confirmed_count} строк${data.rules_affected > 0 ? `, обновлено правил: ${data.rules_affected}` : ''}`);
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['imports', sessionId, 'preview'] }),
        queryClient.invalidateQueries({ queryKey: ['imports', sessionId, 'bulk-clusters'] }),
        queryClient.invalidateQueries({ queryKey: ['imports', sessionId, 'moderation-status'] }),
      ]);
      onApplied();
    },
    onError: (err: Error) => toast.error(err.message || 'Не удалось применить'),
  });

  const includedCount = rows.reduce((acc, r) => acc + (getRowState(r.id).included ? 1 : 0), 0);
  // "Ready to confirm" — the row can go into bulk-apply right now. Count
  // reflects per-row validation (categories where needed, target accounts
  // for transfers, credit account + sums for credit payments, etc.).
  const withCategoryCount = rows.reduce(
    (acc, r) => acc + (rowIsReady(r, getRowState(r.id)) ? 1 : 0),
    0,
  );
  const suggestedCategory =
    bulkCategoryId != null ? categoryById.get(bulkCategoryId)?.name : null;

  // Counterparty items for SearchSelect — all user counterparties, with a
  // "+ Создать «…»" option that appears when the query doesn't match anything.
  const counterpartyItems = useMemo<SearchSelectItem[]>(
    () => counterparties.map((cp) => ({ value: String(cp.id), label: cp.name })),
    [counterparties],
  );
  const trimmedCpQuery = bulkCounterpartyQuery.trim();
  const exactCpMatch = counterparties.some(
    (cp) => cp.name.toLowerCase() === trimmedCpQuery.toLowerCase(),
  );
  const canCreateCounterparty = trimmedCpQuery.length > 0 && !exactCpMatch && !createCounterpartyMutation.isPending;

  // Refund marker — true when *every* fingerprint member of the card is a
  // refund cluster. Applies to fingerprint, brand, and counterparty cards:
  // a brand / counterparty group whose members are all reversals of prior
  // purchases is itself a refund card and should surface the same badge +
  // compensator hint. Without this, a refund that ends up under a
  // counterparty-group view (single-row, counterparty-bound) looks just
  // like a regular income card and the user can't find it.
  const refundMembers: BulkFingerprintCluster[] =
    meta.kind === 'fingerprint'
      ? [meta.cluster]
      : meta.members;
  const isRefundCluster =
    refundMembers.length > 0 && refundMembers.every((m) => Boolean(m.is_refund));
  const refundBrand =
    refundMembers.find((m) => m.refund_brand)?.refund_brand ?? null;
  const refundCounterpartyName =
    meta.kind === 'counterparty'
      ? meta.counterpartyName
      : refundMembers.find((m) => m.refund_resolved_counterparty_name)
          ?.refund_resolved_counterparty_name ?? null;

  const headerNode = (
    <div className="flex w-full items-center gap-3">
      <div className="min-w-0 flex-1">
        <p className="truncate text-base font-semibold text-slate-900">{title}</p>
        <p className="text-sm text-slate-600">{subtitle}</p>
        {isRefundCluster && (
          <p className="mt-0.5 truncate text-xs text-amber-700">
            Возврат
            {refundCounterpartyName
              ? ` · компенсирует расходы «${refundCounterpartyName}»`
              : refundBrand
                ? ` от «${refundBrand}»`
                : ''}
          </p>
        )}
      </div>
      {isRefundCluster && (
        <span className="shrink-0 rounded-full bg-amber-50 px-2.5 py-0.5 text-[11px] font-medium text-amber-700">
          Возврат
        </span>
      )}
      {suggestedCategory ? (
        <span className="shrink-0 rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">
          {suggestedCategory}
        </span>
      ) : (
        <span className="shrink-0 text-xs text-slate-400">Выбери категорию</span>
      )}
      <span
        className={`shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-medium ${
          direction === 'income'
            ? 'bg-emerald-50 text-emerald-700'
            : 'bg-slate-100 text-slate-700'
        }`}
      >
        {direction === 'income' ? 'Доход' : 'Расход'}
      </span>
    </div>
  );

  const bulkPanel = (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
        <div>
          <SearchSelect
            id={`bulk-cat-${title}`}
            label="Категория для всех включённых"
            placeholder="Найти или создать…"
            widthClassName="w-full"
            query={bulkQuery}
            setQuery={setBulkQuery}
            items={categoryItems}
            selectedValue={bulkCategoryId != null ? String(bulkCategoryId) : null}
            onSelect={(item) => {
              setBulkCategoryId(Number(item.value));
              setBulkQuery(item.label);
            }}
            showAllOnFocus
          />
        </div>
        <div>
          <SearchSelect
            id={`bulk-cp-${title}`}
            label="Контрагент (необязательно)"
            placeholder="Найти или создать…"
            widthClassName="w-full"
            query={bulkCounterpartyQuery}
            setQuery={setBulkCounterpartyQuery}
            items={counterpartyItems}
            selectedValue={bulkCounterpartyId != null ? String(bulkCounterpartyId) : null}
            onSelect={(item) => {
              setBulkCounterpartyId(Number(item.value));
              setBulkCounterpartyQuery(item.label);
            }}
            showAllOnFocus
            createAction={{
              visible: canCreateCounterparty,
              label: trimmedCpQuery ? `+ Создать «${trimmedCpQuery}»` : '',
              onClick: () => {
                if (trimmedCpQuery) createCounterpartyMutation.mutate(trimmedCpQuery);
              },
            }}
          />
        </div>
        <div className="flex items-end gap-2">
          <Button
            type="button"
            variant="secondary"
            onClick={applyBulkToAllIncluded}
            disabled={bulkCategoryId == null && bulkCounterpartyId == null}
          >
            Применить ко всем
          </Button>
          <Button
            type="button"
            onClick={() => applyMutation.mutate()}
            disabled={applyMutation.isPending || withCategoryCount === 0}
          >
            {applyMutation.isPending ? (
              <>
                <Loader2 className="mr-2 size-4 animate-spin" />
                Сохраняю…
              </>
            ) : (
              <>Подтвердить {withCategoryCount} / {includedCount}</>
            )}
          </Button>
        </div>
      </div>
      <p className="mt-2 text-xs text-slate-500">
        Снятая галочка откреплёт строку от кластера — она уедет в «Требуют твоего внимания» для индивидуальной обработки.
        Контрагента можно не привязывать. Точечные правки не перезаписываются кнопкой «Применить ко всем».
      </p>
    </div>
  );

  const collapsedNode = (
    <div className="flex w-full items-center gap-3">
      <CollapsibleChevron open={expanded} className="size-4 shrink-0 text-slate-400" />
      {headerNode}
    </div>
  );

  const expandedNode = (
    <div className="flex flex-col gap-4">
      <div className="pr-10">
        {headerNode}
      </div>
      {bulkPanel}
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <ClusterRowList
          rows={rows}
          getRowState={getRowState}
          toggleRowIncluded={toggleRowIncluded}
          detachingRowId={
            detachMutation.isPending
              ? (detachMutation.variables ?? null)
              : null
          }
          setRowCategory={setRowCategory}
          setRowDebtPartner={setRowDebtPartner}
          updateRowState={updateRowState}
          categories={categories}
          filteredCategories={filteredCategories}
          creditAccounts={creditAccounts}
          transferAccounts={transferAccounts}
          counterparties={counterparties}
          debtPartners={debtPartners}
          sessionId={sessionId}
          bulkClusters={bulkClusters}
          onAfterAction={onApplied}
          expanded
        />
      </div>
    </div>
  );

  return (
    <ExpandableCard
      isOpen={expanded}
      onToggle={() => setExpanded((v) => !v)}
      expandedWidth="860px"
      collapsed={collapsedNode}
      expanded={expandedNode}
    />
  );
}

// Row list — simple flow layout (no virtualization) because rows now have
// dynamic heights from the inline operation-type editor. Clusters are
// typically 5-200 rows so the cost is negligible; switching back to the
// virtualizer would require `measureElement` on each expanded row, which
// destabilizes scroll position on every type-toggle.
function ClusterRowList({
  rows,
  getRowState,
  toggleRowIncluded,
  detachingRowId,
  setRowCategory,
  setRowDebtPartner,
  updateRowState,
  categories,
  filteredCategories,
  creditAccounts,
  transferAccounts,
  counterparties,
  debtPartners,
  sessionId,
  bulkClusters,
  onAfterAction,
  expanded = false,
}: {
  rows: ImportPreviewRow[];
  getRowState: (rowId: number) => RowState;
  toggleRowIncluded: (rowId: number) => void;
  detachingRowId: number | null;
  setRowCategory: (rowId: number, categoryId: number | null) => void;
  setRowDebtPartner: (rowId: number, debtPartnerId: number | null) => void;
  updateRowState: (rowId: number, patch: Partial<RowState>) => void;
  categories: Category[];
  filteredCategories: Category[];
  creditAccounts: Account[];
  transferAccounts: Account[];
  counterparties: Counterparty[];
  debtPartners: DebtPartner[];
  sessionId: number;
  bulkClusters?: BulkClustersResponse;
  onAfterAction: () => void;
  expanded?: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const expandedMaxHeight = 'min(58vh, 600px)';

  return (
    <div
      ref={scrollRef}
      className="overflow-y-auto"
      style={{ maxHeight: expanded ? expandedMaxHeight : undefined }}
    >
      {rows.map((row) => {
        const s = getRowState(row.id);
        return (
          <div
            key={row.id}
            className={`border-b border-slate-100 ${s.included ? '' : 'opacity-50'}`}
          >
            {/* Summary row — always visible */}
            <div className="flex items-center gap-3 px-4 py-2 text-sm">
              <input
                type="checkbox"
                checked={s.included}
                onChange={() => toggleRowIncluded(row.id)}
                disabled={detachingRowId === row.id}
                title="Снять галочку — открепить строку от кластера и отправить в «Требуют твоего внимания»"
                className="size-4 shrink-0 disabled:opacity-50"
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="truncate text-slate-800">{descriptionOf(row)}</p>
                  <RowOpTypeBadge op={s.operationType} isRefundRowFallback={isRefundRow(row)} />
                </div>
                <p className="text-xs text-slate-400">#{row.row_index} · {dateOf(row)} · {amountOf(row)}</p>
              </div>
              {/* Picker по типу операции:
                  - regular/refund → категория
                  - debt           → дебитор/кредитор (DebtPartner)
                  - transfer/investment/credit_operation → приглушённая надпись
                  Backend инвариант: для operation_type='debt' counterparty_id
                  отвергается, требуется debt_partner_id (см. CLAUDE.md
                  § Counterparty vs DebtPartner). */}
              {rowNeedsCategory(s.operationType) ? (
                <RowCategoryPicker
                  rowId={row.id}
                  value={s.categoryId}
                  disabled={!s.included}
                  categories={s.operationType === 'refund' ? categories.filter((c) => c.kind === 'expense') : filteredCategories}
                  kindHint={s.operationType === 'refund' ? 'expense' : (filteredCategories[0]?.kind ?? 'expense')}
                  onChange={(id) => setRowCategory(row.id, id)}
                />
              ) : s.operationType === 'debt' ? (
                <RowDebtPartnerPicker
                  rowId={row.id}
                  value={s.debtPartnerId}
                  disabled={!s.included}
                  debtPartners={debtPartners}
                  onChange={(id) => setRowDebtPartner(row.id, id)}
                />
              ) : (
                <span className="w-40 shrink-0 truncate text-right text-xs text-slate-400">
                  категория не нужна
                </span>
              )}
              {/* Edit-type button — opens FLIP modal exactly like "add to counterparty" */}
              <RowEditButton
                row={row}
                state={s}
                disabled={!s.included}
                categories={categories}
                creditAccounts={creditAccounts}
                transferAccounts={transferAccounts}
                counterparties={counterparties}
                debtPartners={debtPartners}
                filteredCategories={filteredCategories}
                onChange={(patch) => updateRowState(row.id, patch)}
              />
              <RowAttachToCounterpartyButton
                row={row}
                sessionId={sessionId}
                bulkClusters={bulkClusters}
                onAttached={onAfterAction}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Small visual tag on each row summary showing its current operation type.
// Keeps refund highlighting (yellow) for refund rows, neutral slate for
// regular. Other types only render a label when explicitly set — reduces
// visual noise in pure-expense clusters.
function RowOpTypeBadge({ op, isRefundRowFallback }: { op: RowOperationType; isRefundRowFallback: boolean }) {
  if (op === 'refund' || (op === 'regular' && isRefundRowFallback)) {
    return (
      <span className="shrink-0 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700">
        Возврат
      </span>
    );
  }
  if (op === 'regular') return null;
  const labels: Record<RowOperationType, string> = {
    regular: 'Обычная',
    transfer: 'Перевод',
    debt: 'Долг',
    refund: 'Возврат',
    investment: 'Инвестиция',
    credit_operation: 'Кредит',
  };
  return (
    <span className="shrink-0 rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] font-medium text-indigo-700">
      {labels[op]}
    </span>
  );
}

// Per-row category picker with type-ahead search + animated dropdown. Same
// behavior as other selects on the import page, scoped to this row only.
// Now supports "+ Новая категория" via CategoryDialog so users can create
// a category without leaving the cluster screen.
function RowCategoryPicker({
  rowId,
  value,
  disabled,
  categories,
  kindHint,
  onChange,
}: {
  rowId: number;
  value: number | null;
  disabled: boolean;
  categories: Category[];
  kindHint?: 'income' | 'expense';
  onChange: (id: number | null) => void;
}) {
  const queryClient = useQueryClient();
  const selected = value != null ? categories.find((c) => c.id === value) ?? null : null;
  const [query, setQuery] = useState<string>(selected?.name ?? '');
  const [dialogOpen, setDialogOpen] = useState(false);
  useEffect(() => {
    setQuery(selected?.name ?? '');
  }, [selected]);
  const items: SearchSelectItem[] = categories.map((c) => ({ value: String(c.id), label: c.name }));

  const trimmed = query.trim();
  const exactMatch = categories.some((c) => c.name.toLowerCase() === trimmed.toLowerCase());
  const canCreate = trimmed.length > 0 && !exactMatch;

  const createMutation = useMutation({
    mutationFn: (payload: CreateCategoryPayload) => createCategory(payload),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ['categories'] });
      setDialogOpen(false);
      onChange(created.id);
      setQuery(created.name);
      toast.success(`Категория «${created.name}» создана`);
    },
    onError: (err: Error) => toast.error(err.message || 'Не удалось создать категорию'),
  });

  // Auto-select when the user typed an exact match but didn't click the
  // dropdown — mirrors the attention-card CategoryPicker behaviour.
  const handleBlur = () => {
    if (value != null) return;
    const q = query.trim().toLowerCase();
    if (!q) return;
    const match = categories.find((c) => c.name.toLowerCase() === q);
    if (match) {
      onChange(match.id);
      setQuery(match.name);
    }
  };

  return (
    <>
      <SearchSelect
        id={`cluster-row-cat-${rowId}`}
        label="Категория"
        hideLabel
        placeholder="— категория —"
        widthClassName="w-40 shrink-0"
        query={query}
        setQuery={setQuery}
        items={items}
        selectedValue={value != null ? String(value) : null}
        onSelect={(item) => {
          onChange(item.value ? Number(item.value) : null);
          setQuery(item.label);
        }}
        onBlur={handleBlur}
        showAllOnFocus
        inputSize="sm"
        disabled={disabled}
        createAction={{
          visible: canCreate && !disabled,
          label: trimmed ? `+ Новая категория «${trimmed}»` : '+ Новая категория',
          onClick: () => setDialogOpen(true),
        }}
      />
      <CategoryDialog
        open={dialogOpen}
        mode="create"
        initialValues={{ kind: kindHint ?? 'expense', name: trimmed || undefined }}
        isSubmitting={createMutation.isPending}
        onClose={() => setDialogOpen(false)}
        onSubmit={(values) => createMutation.mutate(values)}
      />
    </>
  );
}

// Per-row debt-partner picker — используется когда строка кластера выбрана
// как operation_type='debt'. Тот же UX, что и у RowCategoryPicker:
// type-ahead из списка дебиторов/кредиторов + «+ Новый дебитор/кредитор»
// через DebtPartnerDialog (вложенный разворот) без ухода со страницы.
function RowDebtPartnerPicker({
  rowId,
  value,
  disabled,
  debtPartners,
  onChange,
}: {
  rowId: number;
  value: number | null;
  disabled: boolean;
  debtPartners: DebtPartner[];
  onChange: (id: number | null) => void;
}) {
  const queryClient = useQueryClient();
  const selected = value != null ? debtPartners.find((p) => p.id === value) ?? null : null;
  const [query, setQuery] = useState<string>(selected?.name ?? '');
  const [dialogOpen, setDialogOpen] = useState(false);
  useEffect(() => {
    setQuery(selected?.name ?? '');
  }, [selected]);
  const items: SearchSelectItem[] = debtPartners.map((p) => ({ value: String(p.id), label: p.name }));

  const trimmed = query.trim();
  const exactMatch = debtPartners.some((p) => p.name.toLowerCase() === trimmed.toLowerCase());
  const canCreate = trimmed.length > 0 && !exactMatch;

  const createMutation = useMutation({
    mutationFn: (payload: CreateDebtPartnerPayload) => createDebtPartner(payload),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ['debt-partners'] });
      setDialogOpen(false);
      onChange(created.id);
      setQuery(created.name);
      toast.success(`Дебитор/кредитор «${created.name}» создан`);
    },
    onError: (err: Error) => toast.error(err.message || 'Не удалось создать дебитора/кредитора'),
  });

  const handleBlur = () => {
    if (value != null) return;
    const q = query.trim().toLowerCase();
    if (!q) return;
    const match = debtPartners.find((p) => p.name.toLowerCase() === q);
    if (match) {
      onChange(match.id);
      setQuery(match.name);
    }
  };

  return (
    <>
      <SearchSelect
        id={`cluster-row-debt-partner-${rowId}`}
        label="Должник / Кредитор"
        hideLabel
        placeholder="— должник / кредитор —"
        widthClassName="w-40 shrink-0"
        query={query}
        setQuery={setQuery}
        items={items}
        selectedValue={value != null ? String(value) : null}
        onSelect={(item) => {
          onChange(item.value ? Number(item.value) : null);
          setQuery(item.label);
        }}
        onBlur={handleBlur}
        showAllOnFocus
        inputSize="sm"
        disabled={disabled}
        createAction={{
          visible: canCreate && !disabled,
          label: trimmed ? `+ Новый «${trimmed}»` : '+ Новый дебитор/кредитор',
          onClick: () => setDialogOpen(true),
        }}
      />
      <DebtPartnerDialog
        open={dialogOpen}
        draft={{ name: trimmed || undefined }}
        isSubmitting={createMutation.isPending}
        onClose={() => setDialogOpen(false)}
        onSubmit={(payload) => createMutation.mutate(payload)}
      />
    </>
  );
}

// Per-row "→ to counterparty" button inside the cluster row list. Lets the
// user pull one stray row out of a brand cluster and put it under its own
// counterparty. Uses the shared AttachToCounterpartyButton (same FLIP modal
// + picker as the attention-card action).
function RowAttachToCounterpartyButton({
  row,
  sessionId,
  bulkClusters,
  onAttached,
}: {
  row: ImportPreviewRow;
  sessionId: number;
  bulkClusters?: BulkClustersResponse;
  onAttached: () => void;
}) {
  const [open, setOpen] = useState(false);
  const nd = (row.normalized_data || {}) as Record<string, any>;
  const amountRaw = Number(nd.amount ?? 0);
  const direction: 'income' | 'expense' = (nd.direction === 'income' ? 'income' : 'expense');
  const description = descriptionOf(row);

  const mutation = useMutation({
    mutationFn: (cp: { id: number; name: string }) =>
      attachRowToCounterparty(sessionId, row.id, cp.id).then((data) => ({ ...data, _cpName: cp.name })),
    onSuccess: (data) => {
      setOpen(false);
      toast.success(`Добавлено к контрагенту «${data._cpName}»`);
      onAttached();
    },
    onError: (err: Error) => toast.error(err.message || 'Не удалось добавить'),
  });

  return (
    <AttachToCounterpartyButton
      open={open}
      setOpen={setOpen}
      bulkClusters={bulkClusters}
      sourceDirection={direction}
      sourceAmount={Math.abs(amountRaw)}
      sourceDescription={description}
      onAttach={(cp) => mutation.mutate(cp)}
      isPending={mutation.isPending}
      size="sm"
      title="Переместить к контрагенту"
    />
  );
}

function headerFromSkeleton(skeleton: string): string {
  // Simple prettify — take the first 80 chars of the skeleton, capitalize.
  const s = (skeleton || '').trim();
  if (!s) return 'Паттерн';
  const trimmed = s.length > 80 ? s.slice(0, 80) + '…' : s;
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
}

// Build a human-readable title from the cluster's concrete identifier. We
// still show the skeleton verb ("Внешний перевод по номеру") so users can
// tell transfer-types apart, then substitute the <PLACEHOLDER> with the
// real value. Falls back to the skeleton if substitution can't place the
// value meaningfully.
function headerFromIdentifier(
  key: string | null,
  value: string,
  skeleton: string,
): string {
  const placeholderByKey: Record<string, string> = {
    phone: '<PHONE>',
    contract: '<CONTRACT>',
    card: '<CARD>',
    iban: '<IBAN>',
    person_hash: '<PERSON>',
  };
  const placeholder = key ? placeholderByKey[key] : undefined;
  const s = (skeleton || '').trim();
  if (placeholder && s.includes(placeholder.toLowerCase())) {
    const replaced = s.replace(placeholder.toLowerCase(), value);
    const trimmed = replaced.length > 80 ? replaced.slice(0, 80) + '…' : replaced;
    return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
  }
  // Fallback: concatenate skeleton + identifier in parens.
  const base = headerFromSkeleton(skeleton);
  return `${base} · ${value}`;
}

function descriptionOf(row: ImportPreviewRow): string {
  const nd = (row.normalized_data || {}) as Record<string, any>;
  return (
    String(nd.description ?? nd.original_description ?? '') ||
    (row.raw_data as Record<string, string> | undefined)?.description ||
    '—'
  );
}

// Row-level refund detector. Used inside merged counterparty cards where
// refund rows live next to regular expense rows — the badge makes them
// easy to spot at a glance.
function isRefundRow(row: ImportPreviewRow): boolean {
  const nd = (row.normalized_data || {}) as Record<string, any>;
  return Boolean(nd.is_refund) || nd.operation_type === 'refund';
}

function amountOf(row: ImportPreviewRow): string {
  const nd = (row.normalized_data || {}) as Record<string, any>;
  const amount = Number(nd.amount ?? 0);
  const direction = String(nd.direction ?? 'expense');
  const sign = direction === 'income' ? '+' : '−';
  return `${sign} ${formatMoney(amount)}`;
}

function dateOf(row: ImportPreviewRow): string {
  const nd = (row.normalized_data || {}) as Record<string, any>;
  const raw =
    (nd.date as string | undefined) ??
    (nd.operation_date as string | undefined) ??
    (nd.transaction_date as string | undefined) ??
    (row.raw_data as Record<string, string> | undefined)?.date;
  if (!raw) return '—';
  const parsed = new Date(raw);
  if (!Number.isNaN(parsed.getTime())) {
    return new Intl.DateTimeFormat('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: '2-digit',
    }).format(parsed);
  }
  return String(raw);
}

// ============================================================================
// RowEditButton — pencil icon + FLIP modal for per-row operation type editor
// ============================================================================
// Follows the same pattern as AttachToCounterpartyButton: the button saves
// the click coordinate, then the modal animates from that point.

function RowEditButton({
  row,
  state,
  disabled,
  categories,
  filteredCategories,
  creditAccounts,
  transferAccounts,
  counterparties: _cp,
  debtPartners,
  onChange,
}: {
  row: ImportPreviewRow;
  state: RowState;
  disabled: boolean;
  categories: Category[];
  filteredCategories: Category[];
  creditAccounts: Account[];
  transferAccounts: Account[];
  counterparties: Counterparty[];
  debtPartners: DebtPartner[];
  onChange: (patch: Partial<RowState>) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        disabled={disabled}
        title="Изменить тип операции"
        onClick={(e) => {
          (window as any).__lastRowEditClick = { x: e.clientX, y: e.clientY };
          setOpen(true);
        }}
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md border transition ${
          open
            ? 'border-indigo-300 bg-indigo-50 text-indigo-700'
            : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50 hover:text-slate-700'
        } disabled:opacity-50`}
      >
        <Pencil className="size-4" />
      </button>
      <RowEditModal
        isOpen={open}
        onClose={() => setOpen(false)}
        row={row}
        state={state}
        categories={categories}
        filteredCategories={filteredCategories}
        creditAccounts={creditAccounts}
        transferAccounts={transferAccounts}
        debtPartners={debtPartners}
        onChange={(patch) => { onChange(patch); }}
      />
    </>
  );
}

// FLIP modal — identical animation contract to AttachCounterpartyModal.
function RowEditModal({
  isOpen,
  onClose,
  row,
  state,
  categories,
  filteredCategories,
  creditAccounts,
  transferAccounts,
  debtPartners,
  onChange,
}: {
  isOpen: boolean;
  onClose: () => void;
  row: ImportPreviewRow;
  state: RowState;
  categories: Category[];
  filteredCategories: Category[];
  creditAccounts: Account[];
  transferAccounts: Account[];
  debtPartners: DebtPartner[];
  onChange: (patch: Partial<RowState>) => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<'closed' | 'measure' | 'enter' | 'open' | 'exit'>('closed');
  const originRef = useRef<{ x: number; y: number } | null>(null);
  const DURATION = 320;
  const EASING = 'cubic-bezier(0.4, 0, 0.15, 1)';

  useEffect(() => {
    if (isOpen && phase === 'closed') {
      const lastClick = (window as any).__lastRowEditClick as { x: number; y: number } | undefined;
      originRef.current = lastClick ?? { x: window.innerWidth / 2, y: window.innerHeight / 2 };
      setPhase('measure');
    }
  }, [isOpen, phase]);

  useLayoutEffect(() => {
    if (phase !== 'measure') return;
    const panel = panelRef.current;
    const origin = originRef.current;
    if (!panel || !origin) return;
    panel.style.transition = 'none';
    panel.style.transform = 'translate(-50%, -50%) scale(1)';
    panel.style.opacity = '0';
    const rect = panel.getBoundingClientRect();
    const dx = origin.x - (rect.left + rect.width / 2);
    const dy = origin.y - (rect.top + rect.height / 2);
    panel.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(0.05)`;
    panel.getBoundingClientRect();
    panel.style.transition = `transform ${DURATION}ms ${EASING}, opacity ${Math.round(DURATION * 0.6)}ms ease`;
    panel.style.transform = 'translate(-50%, -50%) scale(1)';
    panel.style.opacity = '1';
    setPhase('enter');
  }, [phase]);

  useEffect(() => {
    if (!isOpen && phase !== 'closed' && phase !== 'exit') {
      const panel = panelRef.current;
      const origin = originRef.current;
      if (!panel || !origin) { setPhase('closed'); return; }
      const rect = panel.getBoundingClientRect();
      const dx = origin.x - (rect.left + rect.width / 2);
      const dy = origin.y - (rect.top + rect.height / 2);
      panel.style.transition = `transform ${DURATION}ms ${EASING}, opacity ${Math.round(DURATION * 0.5)}ms ease`;
      panel.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(0.05)`;
      panel.style.opacity = '0';
      setPhase('exit');
    }
  }, [isOpen, phase]);

  const handleTransitionEnd = useCallback(
    (e: React.TransitionEvent) => {
      if (e.propertyName !== 'transform') return;
      if (phase === 'enter') setPhase('open');
      if (phase === 'exit') setPhase('closed');
    },
    [phase],
  );

  useEffect(() => {
    if (phase !== 'exit') return;
    const t = setTimeout(() => setPhase('closed'), DURATION + 100);
    return () => clearTimeout(t);
  }, [phase]);

  useEffect(() => {
    if (phase === 'closed') return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    const sw = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = 'hidden';
    if (sw > 0) document.body.style.paddingRight = `${sw}px`;
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
      document.body.style.paddingRight = '';
    };
  }, [phase, onClose]);

  if (phase === 'closed' || typeof document === 'undefined') return null;
  const backdropVisible = phase === 'enter' || phase === 'open';

  return createPortal(
    <div className="fixed inset-0 z-[9999]">
      {/* backdrop */}
      <div
        onClick={onClose}
        className={`absolute inset-0 bg-black/30 backdrop-blur-[2px] transition-opacity duration-300 ${backdropVisible ? 'opacity-100' : 'opacity-0'}`}
      />
      {/* panel */}
      <div
        ref={panelRef}
        onTransitionEnd={handleTransitionEnd}
        style={{ position: 'fixed', top: '50%', left: '50%', opacity: 0 }}
        className="w-[min(560px,95vw)] rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200"
      >
        <RowEditorContent
          row={row}
          state={state}
          categories={categories}
          filteredCategories={filteredCategories}
          creditAccounts={creditAccounts}
          transferAccounts={transferAccounts}
          debtPartners={debtPartners}
          onChange={onChange}
          onClose={onClose}
        />
      </div>
    </div>,
    document.body,
  );
}

// The actual editor UI inside the modal.
function RowEditorContent({
  row,
  state,
  categories,
  filteredCategories,
  creditAccounts,
  transferAccounts,
  debtPartners,
  onChange,
  onClose,
}: {
  row: ImportPreviewRow;
  state: RowState;
  categories: Category[];
  filteredCategories: Category[];
  creditAccounts: Account[];
  transferAccounts: Account[];
  debtPartners: DebtPartner[];
  onChange: (patch: Partial<RowState>) => void;
  onClose: () => void;
}) {
  const nd = (row.normalized_data ?? {}) as Record<string, unknown>;
  const rowDirection = String(nd.direction ?? 'expense');
  const categoryKind: 'income' | 'expense' =
    state.operationType === 'refund'
      ? 'expense'
      : rowDirection === 'income' ? 'income' : 'expense';
  const availableCategories = useMemo(
    () => categories.filter((c) => c.kind === categoryKind),
    [categories, categoryKind],
  );

  const selectCls = 'h-9 rounded-xl border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 shadow-sm outline-none focus:border-slate-400';

  const opHint: Record<RowOperationType, string> = {
    regular: 'Обычная операция — покупка, услуга, зарплата.',
    transfer: 'Перевод между своими счетами. Категория не нужна.',
    debt: 'Долг между людьми. Укажи направление и должника/кредитора.',
    refund: 'Возврат от продавца. Компенсирует расход в той же категории.',
    investment: 'Покупка или продажа инвестиционного инструмента.',
    credit_operation:
      state.creditKind === 'payment'
        ? 'Платёж по кредиту разделится на проценты (расход) и тело (перевод на кредитный счёт).'
        : state.creditKind === 'early_repayment'
          ? 'Досрочное погашение — перевод на кредитный счёт сверх графика.'
          : 'Выдача кредита — зачисление с кредитного счёта.',
  };

  return (
    <div className="flex flex-col gap-4 p-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-900">{descriptionOf(row)}</p>
          <p className="text-xs text-slate-500">#{row.row_index} · {dateOf(row)} · {amountOf(row)}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
        >
          <X className="size-4" />
        </button>
      </div>

      {/* Operation type selector */}
      <div className="flex flex-col gap-2">
        <label className="text-xs font-medium text-slate-500">Тип операции</label>
        <div className="flex flex-wrap gap-2">
          {(['regular', 'transfer', 'debt', 'refund', 'investment', 'credit_operation'] as RowOperationType[]).map((op) => {
            const labels: Record<RowOperationType, string> = {
              regular: 'Обычная', transfer: 'Перевод', debt: 'Долг',
              refund: 'Возврат', investment: 'Инвестиция', credit_operation: 'Кредитная',
            };
            const active = state.operationType === op;
            return (
              <button
                key={op}
                type="button"
                onClick={() => {
                  const patch: Partial<RowState> = { operationType: op, operationTypeEdited: true };
                  // Долг не использует категорию — debt_partner_id вместо неё.
                  // Все остальные не-категорийные типы тоже сбрасывают категорию.
                  if (op === 'transfer' || op === 'investment' || op === 'credit_operation' || op === 'debt') {
                    patch.categoryId = null;
                    patch.categoryEdited = true;
                  }
                  // Любой не-debt тип отбрасывает выбранного должника
                  // (backend инвариант: debt_partner_id ⇔ operation_type='debt').
                  if (op !== 'debt') {
                    patch.debtPartnerId = null;
                    patch.debtPartnerEdited = true;
                  }
                  onChange(patch);
                }}
                className={`rounded-full px-3.5 py-1.5 text-xs font-medium transition ${
                  active
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                }`}
              >
                {labels[op]}
              </button>
            );
          })}
        </div>
      </div>

      {/* Sub-fields */}
      <div className="flex flex-col gap-3">
        {/* Долг */}
        {state.operationType === 'debt' && (
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-slate-500">Направление долга</label>
            <select value={state.debtDirection} onChange={(e) => onChange({ debtDirection: e.target.value as RowDebtDirection })} className={selectCls}>
              <option value="borrowed">Мне заняли / я взял</option>
              <option value="lent">Я одолжил</option>
              <option value="repaid">Я вернул долг</option>
              <option value="collected">Мне вернули</option>
            </select>
          </div>
        )}

        {/* Инвестиция */}
        {state.operationType === 'investment' && (
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-slate-500">Операция</label>
            <select value={state.investDir} onChange={(e) => onChange({ investDir: e.target.value as RowInvestDir })} className={selectCls}>
              <option value="buy">Покупка</option>
              <option value="sell">Продажа</option>
            </select>
          </div>
        )}

        {/* Кредитная — подтип + кредитный счёт + суммы */}
        {state.operationType === 'credit_operation' && (
          <>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-slate-500">Вид операции</label>
              <select value={state.creditKind} onChange={(e) => onChange({ creditKind: e.target.value as RowCreditKind })} className={selectCls}>
                <option value="disbursement">Получение кредита</option>
                <option value="payment">Платёж по кредиту</option>
                <option value="early_repayment">Досрочное погашение</option>
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-slate-500">Кредитный счёт</label>
              <select value={state.creditAccountId ? String(state.creditAccountId) : ''} onChange={(e) => onChange({ creditAccountId: e.target.value ? Number(e.target.value) : null })} className={selectCls}>
                <option value="">{creditAccounts.length === 0 ? 'Нет кредитных счетов' : '— выбрать —'}</option>
                {creditAccounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
            {state.creditKind === 'payment' && (
              <div className="flex gap-3">
                <div className="flex flex-1 flex-col gap-1.5">
                  <label className="text-xs font-medium text-slate-500">Тело долга, ₽</label>
                  <input type="text" value={state.creditPrincipal} onChange={(e) => onChange({ creditPrincipal: e.target.value })} placeholder="0.00" className={`${selectCls} flex-1`} />
                </div>
                <div className="flex flex-1 flex-col gap-1.5">
                  <label className="text-xs font-medium text-slate-500">Проценты, ₽</label>
                  <input type="text" value={state.creditInterest} onChange={(e) => onChange({ creditInterest: e.target.value })} placeholder="0.00" className={`${selectCls} flex-1`} />
                </div>
              </div>
            )}
          </>
        )}

        {/* Перевод — целевой счёт */}
        {state.operationType === 'transfer' && (
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-slate-500">Счёт назначения</label>
            <select value={state.targetAccountId ? String(state.targetAccountId) : ''} onChange={(e) => onChange({ targetAccountId: e.target.value ? Number(e.target.value) : null })} className={selectCls}>
              <option value="">— выбрать счёт —</option>
              {transferAccounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </div>
        )}

        {/* Категория — только для regular / refund.
            Долг использует не категорию, а ссылку на DebtPartner
            (см. CLAUDE.md § Counterparty vs DebtPartner). */}
        {(state.operationType === 'regular' || state.operationType === 'refund') && (
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-slate-500">Категория</label>
            <RowCategoryPicker
              rowId={row.id}
              value={state.categoryId}
              disabled={false}
              categories={availableCategories}
              kindHint={categoryKind}
              onChange={(id) => onChange({ categoryId: id, categoryEdited: true })}
            />
          </div>
        )}

        {/* Должник/Кредитор — только для debt. */}
        {state.operationType === 'debt' && (
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-slate-500">Должник / Кредитор</label>
            <RowDebtPartnerPicker
              rowId={row.id}
              value={state.debtPartnerId}
              disabled={false}
              debtPartners={debtPartners}
              onChange={(id) => onChange({ debtPartnerId: id, debtPartnerEdited: true })}
            />
          </div>
        )}
      </div>

      {/* Hint + close */}
      <div className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
        <p className="text-xs text-slate-500">{opHint[state.operationType]}</p>
        <button
          type="button"
          onClick={onClose}
          className="ml-4 shrink-0 rounded-lg bg-indigo-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
        >
          Готово
        </button>
      </div>
    </div>
  );
}

export const ClusterCard = memo(ClusterCardImpl);
