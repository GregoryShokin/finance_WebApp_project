'use client';

/**
 * Floating action cluster, bottom-right of the import page.
 *  - Plus: open file dialog (upload new statement)
 *  - Red: excluded rows (status = 'skipped')
 *  - Amber: parked rows (status = 'parked')
 *  - Green: ready rows (status = 'ready')
 *  - Queue pill: re-uses the same QueuePanel as the action bar
 *
 * Each colored button opens a popover modal listing rows of that bucket with
 * detail chips (type / category-or-direction / counterparty / split badge),
 * an "Изменить" action to deep-edit the row, and "Вернуть" for snz/excl.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'framer-motion';
import { Banknote, Check, Clock4, FileText, Landmark, Link as LinkIcon, ListTree, Pencil, PiggyBank, Plus, Trash2, User, Wallet, X } from 'lucide-react';
import { toast } from 'sonner';

import { Chip } from '@/components/ui/status-chip';
import { CategoryDialog } from '@/components/categories/category-dialog';
import { AccountDialog } from '@/components/accounts/account-dialog';
import { fmtDateShort, fmtRubAbs, fmtRubSigned } from './format';
import {
  TYPE_OPTIONS,
  DEBT_DIR_OPTIONS,
  CREDIT_KIND_OPTIONS,
  INVEST_DIR_OPTIONS,
  investmentDirFor,
  operationTypeToCreditKind,
} from './option-sets';
import { SplitChip } from './split-chip';
import { EditTxRazvorot } from './edit-tx-razvorot';
import {
  unexcludeImportRow,
  unparkImportRow,
} from '@/lib/api/imports';
import { createCategory, getCategories } from '@/lib/api/categories';
import { createCounterparty, getCounterparties } from '@/lib/api/counterparties';
import { createAccount, getAccounts } from '@/lib/api/accounts';
import type { CreateAccountPayload } from '@/types/account';
import type { CreateCategoryPayload } from '@/types/category';
import type { ImportPreviewResponse, ImportPreviewRow, ImportSplitItem } from '@/types/import';

type Bucket = 'done' | 'snz' | 'excl' | 'transfers_dupes';

const BUCKET_CFG: Record<Bucket, { bg: string; title: string }> = {
  done:             { bg: '#1e8a4f', title: 'Проверено' },
  snz:              { bg: '#d49b1a', title: 'Отложено' },
  excl:             { bg: '#e54033', title: 'Исключено' },
  transfers_dupes:  { bg: '#1d4f8a', title: 'Переводы и дубли' },
};

function isTransferOrDuplicate(r: ImportPreviewRow): boolean {
  if (r.status === 'duplicate') return true;
  const nd = r.normalized_data as Record<string, unknown> | undefined;
  // (1) TransferMatcher found a partner row in the same statement → has
  // transfer_match_meta. (2) Recognition decided this is a transfer based on
  // the description alone (e.g. «Внутрибанковский перевод с договора…»)
  // and set operation_type='transfer' + target_account_id, but the partner
  // side lives in a different statement we don't have here. Both cases are
  // self-transfers and don't represent income/expense.
  if (nd?.transfer_match_meta) return true;
  if (nd?.operation_type === 'transfer') return true;
  return false;
}

function bucketize(rows: ImportPreviewRow[], bucket: Bucket): ImportPreviewRow[] {
  if (bucket === 'snz') return rows.filter((r) => r.status === 'parked');
  if (bucket === 'excl') return rows.filter((r) => r.status === 'skipped');
  if (bucket === 'transfers_dupes') return rows.filter(isTransferOrDuplicate);
  return rows.filter((r) => r.status === 'ready');
}

function sumAmount(rows: ImportPreviewRow[]): number {
  let s = 0;
  for (const r of rows) {
    const nd = r.normalized_data as Record<string, unknown> | undefined;
    const v = (nd?.amount as string | number | null) ?? r.raw_data?.amount ?? null;
    const n = typeof v === 'string' ? Number(v) : (v as number | null);
    if (Number.isFinite(n)) s += Math.abs(n as number);
  }
  return s;
}

export function ImportFabCluster({
  preview,
  onOpenQueue,
}: {
  preview: ImportPreviewResponse | null;
  onOpenQueue: () => void;
}) {
  const [open, setOpen] = useState<{ bucket: Bucket; origin: { x: number; y: number } } | null>(null);

  const rows = preview?.rows ?? [];
  const counts = {
    done:            bucketize(rows, 'done').length,
    snz:             bucketize(rows, 'snz').length,
    excl:            bucketize(rows, 'excl').length,
    transfers_dupes: bucketize(rows, 'transfers_dupes').length,
  };

  return (
    <>
      <div className="pointer-events-none fixed bottom-6 right-6 z-30 flex flex-col items-end gap-3">
        <button
          type="button"
          onClick={onOpenQueue}
          className="pointer-events-auto inline-flex h-10 items-center gap-2 rounded-pill border border-line bg-bg-surface px-3 text-xs font-medium text-ink shadow-pillHover transition hover:-translate-y-px"
        >
          <FileText className="size-3.5 text-ink-3" />
          Очередь
        </button>

        <FabBubble bucket="done"            count={counts.done}            onClick={(e) => setOpen({ bucket: 'done',            origin: getOrigin(e) })} />
        <FabBubble bucket="transfers_dupes" count={counts.transfers_dupes} onClick={(e) => setOpen({ bucket: 'transfers_dupes', origin: getOrigin(e) })} />
        <FabBubble bucket="snz"             count={counts.snz}             onClick={(e) => setOpen({ bucket: 'snz',             origin: getOrigin(e) })} />
        <FabBubble bucket="excl"            count={counts.excl}            onClick={(e) => setOpen({ bucket: 'excl',            origin: getOrigin(e) })} />

        <CreateEntityFab />
      </div>

      <AnimatePresence>
        {open ? (
          <BucketPanel
            bucket={open.bucket}
            origin={open.origin}
            rows={bucketize(rows, open.bucket)}
            onClose={() => setOpen(null)}
          />
        ) : null}
      </AnimatePresence>
    </>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// CreateEntityFab — primary `+` FAB. Click pops up a small menu with quick
// links to create a Category / Account / Credit account / Deposit account.
// Each item opens the corresponding existing dialog (CategoryDialog or
// AccountDialog with a preset account_type).

type EntityKind = 'category' | 'account' | 'credit' | 'deposit';

const ENTITY_ITEMS: Array<{
  kind: EntityKind;
  label: string;
  Icon: React.ComponentType<{ className?: string }>;
  tone: string; // bg color
}> = [
  { kind: 'category', label: 'Категория',     Icon: ListTree,   tone: '#5b3a8a' },
  { kind: 'account',  label: 'Счёт',          Icon: Wallet,     tone: '#1d4f8a' },
  { kind: 'credit',   label: 'Кредит',        Icon: Landmark,   tone: '#8b1f1f' },
  { kind: 'deposit',  label: 'Вклад',         Icon: PiggyBank,  tone: '#14613b' },
];

function CreateEntityFab() {
  const queryClient = useQueryClient();
  const [menuOpen, setMenuOpen] = useState(false);
  const [creating, setCreating] = useState<EntityKind | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current?.contains(e.target as Node)) return;
      setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenuOpen(false); };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuOpen]);

  const categoryMut = useMutation({
    mutationFn: (payload: CreateCategoryPayload) => createCategory(payload),
    onSuccess: async (cat) => {
      await queryClient.invalidateQueries({ queryKey: ['categories'] });
      toast.success(`Категория «${cat.name}» создана`);
      setCreating(null);
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось создать категорию'),
  });

  const accountMut = useMutation({
    mutationFn: (payload: CreateAccountPayload) => createAccount(payload),
    onSuccess: async (acc) => {
      await queryClient.invalidateQueries({ queryKey: ['accounts'] });
      toast.success(`«${acc.name}» создан`);
      setCreating(null);
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось создать счёт'),
  });

  // Preset for AccountDialog depending on which menu item was picked.
  const accountInitial: Partial<CreateAccountPayload> | null =
    creating === 'credit'
      ? { account_type: 'credit_card', is_credit: true }
      : creating === 'deposit'
        ? { account_type: 'savings', is_credit: false }
        : creating === 'account'
          ? { account_type: 'main', is_credit: false }
          : null;

  return (
    <div ref={wrapRef} className="pointer-events-auto relative">
      <AnimatePresence>
        {menuOpen ? (
          <motion.div
            key="entity-menu"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0, transition: { duration: 0.16 } }}
            exit={{ opacity: 0, y: 6, transition: { duration: 0.12 } }}
            className="absolute bottom-[68px] right-0 flex flex-col items-end gap-2"
          >
            {ENTITY_ITEMS.map(({ kind, label, Icon, tone }) => (
              <button
                key={kind}
                type="button"
                onClick={() => {
                  setMenuOpen(false);
                  setCreating(kind);
                }}
                className="inline-flex items-center gap-2.5 rounded-pill border border-line bg-bg-surface px-3.5 py-2 text-xs font-medium text-ink shadow-pillHover transition hover:-translate-y-px"
              >
                <span className="grid size-7 place-items-center rounded-full text-white" style={{ background: tone }}>
                  <Icon className="size-3.5" />
                </span>
                {label}
              </button>
            ))}
          </motion.div>
        ) : null}
      </AnimatePresence>

      <button
        type="button"
        onClick={() => setMenuOpen((v) => !v)}
        className="grid size-14 place-items-center rounded-full bg-ink text-white shadow-fabActive transition hover:scale-105"
        title="Создать категорию, счёт, кредит или вклад"
      >
        <Plus className={`size-6 transition-transform ${menuOpen ? 'rotate-45' : ''}`} />
      </button>

      <CategoryDialog
        open={creating === 'category'}
        mode="create"
        initialValues={null}
        isSubmitting={categoryMut.isPending}
        onClose={() => setCreating(null)}
        onSubmit={(values) => categoryMut.mutate(values)}
      />
      <AccountDialog
        open={creating === 'account' || creating === 'credit' || creating === 'deposit'}
        mode="create"
        initialValues={accountInitial}
        isSubmitting={accountMut.isPending}
        onClose={() => setCreating(null)}
        onSubmit={(values) => accountMut.mutate(values)}
      />
    </div>
  );
}

// Suppress unused-import warning for entity helpers referenced by other files.
void createCounterparty;

function getOrigin(e: React.MouseEvent<HTMLButtonElement>) {
  const r = e.currentTarget.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}

// ──────────────────────────────────────────────────────────────────────────

function FabBubble({
  bucket,
  count,
  onClick,
}: {
  bucket: Bucket;
  count: number;
  onClick: (e: React.MouseEvent<HTMLButtonElement>) => void;
}) {
  const cfg = BUCKET_CFG[bucket];
  const Icon =
    bucket === 'done' ? Check :
    bucket === 'snz' ? Clock4 :
    bucket === 'excl' ? Trash2 :
    LinkIcon;
  return (
    <button
      type="button"
      onClick={onClick}
      title={cfg.title}
      style={{ background: cfg.bg }}
      className="pointer-events-auto relative grid size-12 place-items-center rounded-full text-white shadow-fab transition hover:-translate-y-px hover:scale-105"
    >
      <Icon className="size-[18px]" />
      {count > 0 ? (
        <span
          className="absolute -right-1 -top-1 grid h-5 min-w-[20px] place-items-center rounded-full border-2 px-1 font-mono text-[10px] font-bold"
          style={{ background: '#fff', borderColor: cfg.bg, color: cfg.bg }}
        >
          {count}
        </span>
      ) : null}
    </button>
  );
}

// ──────────────────────────────────────────────────────────────────────────

function BucketPanel({
  bucket,
  origin,
  rows,
  onClose,
}: {
  bucket: Bucket;
  origin: { x: number; y: number };
  rows: ImportPreviewRow[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const cfg = BUCKET_CFG[bucket];
  const Icon =
    bucket === 'done' ? Check :
    bucket === 'snz' ? Clock4 :
    bucket === 'excl' ? Trash2 :
    LinkIcon;
  const totalAmt = sumAmount(rows);

  // Lookup maps for chip rendering
  const categoriesQuery     = useQuery({ queryKey: ['categories'],     queryFn: () => getCategories() });
  const counterpartiesQuery = useQuery({ queryKey: ['counterparties'], queryFn: getCounterparties });
  const accountsQuery       = useQuery({ queryKey: ['accounts'],       queryFn: getAccounts });

  const categoriesById = useMemo(() => {
    const m = new Map<number, string>();
    for (const c of categoriesQuery.data ?? []) m.set(c.id, c.name);
    return m;
  }, [categoriesQuery.data]);
  const counterpartiesById = useMemo(() => {
    const m = new Map<number, string>();
    for (const c of counterpartiesQuery.data ?? []) m.set(c.id, c.name);
    return m;
  }, [counterpartiesQuery.data]);
  const accountsById = useMemo(() => {
    const m = new Map<number, string>();
    for (const a of accountsQuery.data ?? []) m.set(a.id, a.name);
    return m;
  }, [accountsQuery.data]);

  const restoreMut = useMutation({
    mutationFn: async (rowId: number) => {
      if (bucket === 'excl') return unexcludeImportRow(rowId);
      if (bucket === 'snz')  return unparkImportRow(rowId);
      // transfers_dupes — backend "unpair" endpoint is not yet available.
      throw new Error('Разрыв пары / снятие метки дубликата ещё не подключены к бэку');
    },
    onSuccess: () => {
      toast.success('Возвращено в обработку');
      queryClient.invalidateQueries({ queryKey: ['imports', 'preview'] });
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось'),
  });

  const [editing, setEditing] = useState<{ row: ImportPreviewRow; origin: { x: number; y: number } } | null>(null);

  const subtitle =
    bucket === 'done'
      ? `${rows.length} операций · ${fmtRubAbs(totalAmt)} — готовы к импорту`
      : bucket === 'snz'
        ? `${rows.length} отложено · ${fmtRubAbs(totalAmt)}`
        : bucket === 'excl'
          ? `${rows.length} исключено · ${fmtRubAbs(totalAmt)}`
          : `${rows.length} операций объединены в пары`;

  const footer =
    bucket === 'done'
      ? 'Эти строки помечены «готовы»: категории проставлены, ошибок нет. Жми «Импортировать готовые», чтобы создать транзакции разом.'
      : bucket === 'snz'
        ? 'Эти строки пока не размечены — мы не будем их импортировать, пока ты не примешь решение.'
        : bucket === 'excl'
          ? 'Эти строки исключены из импорта. Можно вернуть отдельную строку или восстановить все целиком.'
          : 'Переводы между своими счетами и обнаруженные дубликаты. Их сумма не учитывается как доход/расход. Разрыв пары пока не реализован — нужен новый бэкенд-эндпоинт.';

  return createPortal(
    <>
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
          className="pointer-events-auto flex max-h-[80vh] w-[min(680px,92vw)] flex-col overflow-hidden rounded-3xl border border-line bg-bg-surface shadow-modal"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center gap-3 border-b border-line px-5 py-4">
            <span className="grid size-8 place-items-center rounded-full text-white" style={{ background: cfg.bg }}>
              <Icon className="size-3.5" />
            </span>
            <div className="flex-1">
              <div className="text-[15px] font-semibold text-ink">{cfg.title}</div>
              <div className="mt-0.5 text-xs text-ink-3">{subtitle}</div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="grid size-8 place-items-center rounded-full text-ink-3 transition hover:bg-ink/5"
            >
              <X className="size-3.5" />
            </button>
          </div>

          <div className="overflow-auto px-2 py-1">
            {rows.length === 0 ? (
              <div className="grid h-32 place-items-center text-xs text-ink-3">Список пуст.</div>
            ) : (
              rows.map((r) => (
                <BucketRow
                  key={r.id}
                  row={r}
                  bucket={bucket}
                  categoriesById={categoriesById}
                  counterpartiesById={counterpartiesById}
                  accountsById={accountsById}
                  onRestore={() => restoreMut.mutate(r.id)}
                  onEdit={(o) => setEditing({ row: r, origin: o })}
                />
              ))
            )}
          </div>

          <footer className="border-t border-line bg-bg-surface2 px-5 py-3 text-[11.5px] leading-snug text-ink-3">
            {footer}
          </footer>
        </motion.div>
      </div>

      {editing ? (
        <EditTxRazvorot
          sessionId={0}
          row={editing.row}
          origin={editing.origin}
          options={{
            categories: (categoriesQuery.data ?? []).map((c) => ({
              value: String(c.id), label: c.name,
            })),
          }}
          onClose={() => setEditing(null)}
        />
      ) : null}
    </>,
    document.body,
  );
}

// ──────────────────────────────────────────────────────────────────────────

function BucketRow({
  row,
  bucket,
  categoriesById,
  counterpartiesById,
  accountsById,
  onRestore,
  onEdit,
}: {
  row: ImportPreviewRow;
  bucket: Bucket;
  categoriesById: Map<number, string>;
  counterpartiesById: Map<number, string>;
  accountsById: Map<number, string>;
  onRestore: () => void;
  onEdit: (origin: { x: number; y: number }) => void;
}) {
  const nd = (row.normalized_data ?? {}) as Record<string, unknown>;
  const date = (nd.date as string) || (row.raw_data?.date as string) || '';
  const desc = (nd.description as string) || (row.raw_data?.description as string) || '';
  const amount = (nd.amount as string | number | null) ?? row.raw_data?.amount ?? null;
  const dir: 'income' | 'expense' = ((nd.direction as 'income' | 'expense') || 'expense');

  const opType = (nd.operation_type as string | undefined) ?? 'regular';
  const t = mapOperationToType(opType);
  const typeOpt = TYPE_OPTIONS.find((x) => x.value === t) ?? TYPE_OPTIONS[0];
  const splitItems = (nd.split_items as ImportSplitItem[] | undefined) ?? null;
  const cpName = (nd.counterparty_id as number | null) != null
    ? counterpartiesById.get(nd.counterparty_id as number)
    : null;

  return (
    <div className="grid grid-cols-[50px_1fr_auto_auto] items-start gap-3 rounded-xl px-3 py-2.5 transition hover:bg-bg-surface2">
      <span className="pt-1 font-mono text-[11px] text-ink-3">{fmtDateShort(date)}</span>

      <div className="min-w-0">
        <div className="truncate text-[12.5px]">{desc || '(без описания)'}</div>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {splitItems && splitItems.length > 0 ? (
            <SplitChip
              parts={splitItems}
              categoriesById={categoriesById}
              counterpartiesById={counterpartiesById}
            />
          ) : (
            <>
              <Chip tone="line">
                <span
                  className="size-1.5 rounded-full"
                  style={{ background: typeOpt.toneDot ?? '#8a8b91' }}
                />
                {typeOpt.label}
              </Chip>
              {detailChip(t, nd, dir, bucket, categoriesById, accountsById)}
            </>
          )}
          {cpName && (!splitItems || splitItems.length === 0) ? (
            <Chip tone="violet">
              <User className="size-2.5" />
              {cpName}
            </Chip>
          ) : null}
        </div>
      </div>

      <span
        className={`min-w-[90px] text-right font-mono text-[12.5px] font-semibold tabular-nums ${
          dir === 'income' ? 'text-accent-green' : 'text-ink'
        }`}
      >
        {fmtRubSigned(amount as number | string | null | undefined, dir)}
      </span>

      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            onEdit({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
          }}
          className="grid size-7 place-items-center rounded-md text-ink-3 transition hover:bg-bg-surface2 hover:text-ink"
          title="Изменить"
        >
          <Pencil className="size-3" />
        </button>
        {bucket !== 'done' ? (
          <button
            type="button"
            onClick={onRestore}
            className="rounded-lg px-2 py-1 text-[11px] text-ink-3 transition hover:bg-bg-surface2 hover:text-ink"
          >
            Вернуть
          </button>
        ) : null}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Helpers — type mapping + detail chip per type

function mapOperationToType(opType: string): string {
  if (opType === 'debt') return 'debt';
  if (opType === 'transfer') return 'transfer';
  if (opType === 'refund') return 'refund';
  if (opType === 'investment_buy' || opType === 'investment_sell') return 'investment';
  if (opType === 'credit_disbursement' || opType === 'credit_payment' || opType === 'credit_early_repayment') {
    return 'credit_operation';
  }
  return 'regular';
}

function detailChip(
  t: string,
  nd: Record<string, unknown>,
  direction: 'income' | 'expense' | string,
  bucket: Bucket,
  categoriesById: Map<number, string>,
  accountsById: Map<number, string>,
) {
  if (t === 'regular' || t === 'refund') {
    const catId = nd.category_id as number | null | undefined;
    if (catId == null) return null;
    const name = categoriesById.get(catId);
    if (!name) return null;
    const tone = bucket === 'done' ? 'green' : bucket === 'snz' ? 'amber' : 'red';
    return (
      <Chip tone={tone}>
        {bucket === 'done' ? <Check className="size-2.5" /> : null}
        {name}
      </Chip>
    );
  }
  if (t === 'debt') {
    const dir = DEBT_DIR_OPTIONS.find((x) => x.value === (nd.debt_direction as string));
    if (!dir) return null;
    return <Chip tone="line">{dir.label}</Chip>;
  }
  if (t === 'investment') {
    const v = investmentDirFor(direction);
    const dir = INVEST_DIR_OPTIONS.find((x) => x.value === v);
    if (!dir) return null;
    return (
      <Chip tone="line">
        <span className="size-1.5 rounded-full" style={{ background: dir.toneDot ?? '#8a8b91' }} />
        {dir.label}
      </Chip>
    );
  }
  if (t === 'credit_operation') {
    const opType = nd.operation_type as string | undefined;
    const k = operationTypeToCreditKind(opType);
    const opt = CREDIT_KIND_OPTIONS.find((x) => x.value === k);
    if (!opt) return null;
    return <Chip tone="line">{opt.label}</Chip>;
  }
  if (t === 'transfer') {
    const accId = nd.target_account_id as number | null | undefined;
    if (accId == null) return null;
    const accName = accountsById.get(accId);
    if (!accName) return null;
    // Income transfer (money in) → blue, prefix «↓ на»
    // Expense transfer (money out) → orange, prefix «↑ с»
    const isIncome = direction === 'income';
    return (
      <span
        className="inline-flex items-center gap-1 rounded-pill px-2 py-0.5 text-[11px] font-medium leading-tight"
        style={{
          background: isIncome ? 'var(--tw-bg-accent-blue-soft, #e3edf8)' : '#fdebd0',
          color: isIncome ? '#1d4f8a' : '#c47700',
        }}
      >
        {isIncome ? '↓ на' : '↑ с'} {accName}
      </span>
    );
  }
  return null;
}
