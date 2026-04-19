"use client";

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRightLeft, CheckCircle2, Plus, RotateCcw, ShieldAlert, Trash2 } from 'lucide-react';
import { CategoryIcon } from '@/components/categories/category-icon';
import { toast } from 'sonner';

import { PageShell } from '@/components/layout/page-shell';
import { ErrorState, EmptyState, LoadingState } from '@/components/states/page-state';
import { AccountDialog } from '@/components/accounts/account-dialog';
import { CategoryDialog } from '@/components/categories/category-dialog';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { SearchSelect, type SearchSelectItem } from '@/components/ui/search-select';
import { StatCard } from '@/components/shared/stat-card';
import { MoneyAmount } from '@/components/shared/money-amount';
import { StatusBadge } from '@/components/shared/status-badge';
import { getAccounts, createAccount } from '@/lib/api/accounts';
import { getCategories, createCategory } from '@/lib/api/categories';
import { deleteTransaction, getTransactions, splitTransaction, updateTransaction } from '@/lib/api/transactions';
import { getImportReviewQueue } from '@/lib/api/imports';
import { formatDateTime } from '@/lib/utils/format';
import type { CreateAccountPayload } from '@/types/account';
import type { CategoryKind, CategoryPriority, CategoryPriority as CategoryPriorityType, CreateCategoryPayload } from '@/types/category';
import type {
  CreateTransactionPayload,
  SplitTransactionPayload,
  Transaction,
  TransactionKind,
  TransactionOperationType,
} from '@/types/transaction';
import type { ImportReviewRow } from '@/types/import';
import { operationTypeLabels, transactionTypeLabels } from '@/components/transactions/constants';
import { useDelayedDelete } from '@/hooks/use-delayed-delete';

const priorityLabels: Record<CategoryPriority, string> = {
  expense_essential: 'Обязательный',
  expense_secondary: 'Второстепенный',
  expense_target: 'Имущество',
  income_active: 'Активный доход',
  income_passive: 'Пассивный доход',
};

const defaultCategoryPriorityByKind: Record<CategoryKind, CategoryPriorityType> = {
  expense: 'expense_secondary',
  income: 'income_active',
};


const EMPTY_SPLIT_ROW = { category_id: '', category_query: '', amount: '', description: '' };

type ReviewFormState = {
  account_id: string;
  target_account_id: string;
  category_id: string;
  amount: string;
  type: TransactionKind;
  operation_type: TransactionOperationType;
  description: string;
};

type SplitRow = {
  category_id: string;
  category_query: string;
  amount: string;
  description: string;
};

function normalize(value: string) {
  return value.trim().toLowerCase();
}

function getPriorityTone(priority?: CategoryPriority | null) {
  switch (priority) {
    case 'expense_essential':
      return 'expense';
    case 'expense_secondary':
      return 'warning';
    case 'expense_target':
      return 'info';
    case 'income_active':
    case 'income_passive':
      return 'income';
    default:
      return 'neutral';
  }
}

function buildInitialForm(transaction: Transaction): ReviewFormState {
  return {
    account_id: String(transaction.account_id),
    target_account_id: transaction.target_account_id ? String(transaction.target_account_id) : '',
    category_id: transaction.category_id ? String(transaction.category_id) : '',
    amount: String(transaction.amount),
    type: transaction.type,
    operation_type: transaction.operation_type,
    description: transaction.description ?? '',
  };
}

function isTransfer(operationType: TransactionOperationType) {
  return operationType === 'transfer';
}

function shouldShowCategory(operationType: TransactionOperationType) {
  return operationType === 'regular' || operationType === 'refund';
}

function isExpenseLike(operationType: TransactionOperationType, type: TransactionKind) {
  return operationType === 'refund' || type === 'expense';
}

function canConfirm(form: ReviewFormState) {
  if (!form.account_id) return false;
  if (isTransfer(form.operation_type)) {
    return Boolean(form.target_account_id && form.account_id !== form.target_account_id);
  }
  if (shouldShowCategory(form.operation_type)) {
    return Boolean(form.category_id);
  }
  return true;
}

function buildPayload(form: ReviewFormState, currency: string): CreateTransactionPayload {
  return {
    account_id: Number(form.account_id),
    target_account_id: isTransfer(form.operation_type)
      ? (form.target_account_id ? Number(form.target_account_id) : null)
      : null,
    category_id: shouldShowCategory(form.operation_type)
      ? (form.category_id ? Number(form.category_id) : null)
      : null,
    amount: Number(form.amount),
    currency,
    type: form.type,
    operation_type: form.operation_type,
    description: form.description || null,
    transaction_date: new Date().toISOString(),
    needs_review: false,
  };
}

function getOperationOptionItems(): SearchSelectItem[] {
  return [
    { value: 'regular', label: 'Обычный', searchText: 'обычный regular расход доход' },
    { value: 'transfer', label: 'Перевод', searchText: 'перевод между счетами transfer' },
    { value: 'refund', label: 'Возврат', searchText: 'возврат refund' },
    { value: 'adjustment', label: 'Корректировка', searchText: 'корректировка adjustment' },
  ];
}

function getOperationLabel(value: TransactionOperationType) {
  if (value === 'transfer') return 'Перевод';
  if (value === 'refund') return 'Возврат';
  if (value === 'adjustment') return 'Корректировка';
  return operationTypeLabels[value] ?? value;
}



function formatImportAmount(row: ImportReviewRow) {
  const amount = Number(row.normalized_data.amount ?? 0);
  const type = String(row.normalized_data.type ?? 'expense');
  return type === 'income' ? amount : -amount;
}

function inferTypeByOperation(operationType: TransactionOperationType, currentType: TransactionKind): TransactionKind {
  if (operationType === 'refund') return 'income';
  if (operationType === 'transfer') return 'expense';
  return currentType;
}

export default function ReviewPage() {
  const queryClient = useQueryClient();
  const [forms, setForms] = useState<Record<number, ReviewFormState>>({});
  const [formQueries, setFormQueries] = useState<Record<number, Record<string, string>>>({});
  const [splitTransactionId, setSplitTransactionId] = useState<number | null>(null);
  const [splitRows, setSplitRows] = useState<SplitRow[]>([{ ...EMPTY_SPLIT_ROW }, { ...EMPTY_SPLIT_ROW }]);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const delayedDelete = useDelayedDelete();
  const [accountDialogOpen, setAccountDialogOpen] = useState(false);
  const [categoryDialogOpen, setCategoryDialogOpen] = useState(false);
  const [pendingAccountDraft, setPendingAccountDraft] = useState<Partial<CreateAccountPayload> | null>(null);
  const [pendingCategoryDraft, setPendingCategoryDraft] = useState<Partial<CreateCategoryPayload> | null>(null);

  const accountsQuery = useQuery({ queryKey: ['accounts'], queryFn: getAccounts });
  const categoriesQuery = useQuery({ queryKey: ['categories', 'review'], queryFn: () => getCategories() });
  const transactionsQuery = useQuery({
    queryKey: ['transactions', 'review-only'],
    queryFn: () => getTransactions({ needs_review: true }),
    enabled: accountsQuery.isSuccess && categoriesQuery.isSuccess,
  });
  const importReviewQueueQuery = useQuery({
    queryKey: ['imports', 'review-queue'],
    queryFn: getImportReviewQueue,
    enabled: accountsQuery.isSuccess && categoriesQuery.isSuccess,
  });

  const invalidateAll = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['transactions'] }),
      queryClient.invalidateQueries({ queryKey: ['accounts'] }),
      queryClient.invalidateQueries({ queryKey: ['categories'] }),
    ]);
  };

  const confirmMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: CreateTransactionPayload }) => updateTransaction(id, payload),
    onSuccess: async (updated) => {
      toast.success('Операция подтверждена');
      setForms((prev) => {
        const next = { ...prev };
        delete next[updated.id];
        return next;
      });
      setFormQueries((prev) => {
        const next = { ...prev };
        delete next[updated.id];
        return next;
      });
      await invalidateAll();
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось подтвердить операцию'),
  });

  const deleteMutation = useMutation({
    mutationFn: (transactionId: number) => deleteTransaction(transactionId),
    onMutate: (transactionId) => setDeletingId(transactionId),
    onSuccess: async (_, transactionId) => {
      toast.success('Транзакция удалена');
      setForms((prev) => {
        const next = { ...prev };
        delete next[transactionId];
        return next;
      });
      setFormQueries((prev) => {
        const next = { ...prev };
        delete next[transactionId];
        return next;
      });
      await invalidateAll();
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось удалить транзакцию'),
    onSettled: () => setDeletingId(null),
  });

  const splitMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: SplitTransactionPayload }) => splitTransaction(id, payload),
    onSuccess: async () => {
      toast.success('Транзакция разбита по категориям');
      setSplitTransactionId(null);
      setSplitRows([{ ...EMPTY_SPLIT_ROW }, { ...EMPTY_SPLIT_ROW }]);
      await invalidateAll();
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось разбить транзакцию'),
  });

  const createAccountMutation = useMutation({
    mutationFn: createAccount,
    onSuccess: async () => {
      toast.success('Счёт создан');
      setAccountDialogOpen(false);
      await queryClient.invalidateQueries({ queryKey: ['accounts'] });
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось создать счёт'),
  });

  const createCategoryMutation = useMutation({
    mutationFn: createCategory,
    onSuccess: async () => {
      toast.success('Категория создана');
      setCategoryDialogOpen(false);
      await queryClient.invalidateQueries({ queryKey: ['categories'] });
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось создать категорию'),
  });

  const transactions = transactionsQuery.data ?? [];
  const importReviewRows = importReviewQueueQuery.data?.rows ?? [];
  const accounts = accountsQuery.data ?? [];
  const categories = categoriesQuery.data ?? [];

  const expenseCategories = useMemo(() => categories.filter((item) => item.kind === 'expense'), [categories]);

  const accountItems = useMemo<SearchSelectItem[]>(
    () =>
      accounts.map((account) => ({
        value: String(account.id),
        label: account.name,
        searchText: `${account.name} ${account.currency}`,
        badge: account.currency,
      })),
    [accounts],
  );

  const categoryItems = useMemo<SearchSelectItem[]>(
    () =>
      [...categories]
        .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
        .map((category) => ({
          value: String(category.id),
          label: category.name,
          searchText: `${category.name} ${category.kind}`,
          badge: category.kind === 'income' ? 'Доход' : 'Расход',
          badgeClassName: category.kind === 'income' ? 'text-emerald-600' : 'text-rose-600',
        })),
    [categories],
  );

  const operationItems = useMemo(() => getOperationOptionItems(), []);

  const stats = useMemo(() => {
    const totalAmount = transactions.reduce((acc, item) => acc + (item.type === 'expense' ? -Number(item.amount) : Number(item.amount)), 0);
    const uncategorized = transactions.filter((item) => !item.category_id && item.operation_type !== 'transfer').length;
    const incompleteTransfers = transactions.filter((item) => item.operation_type === 'transfer' && !item.target_account_id).length;
    return { total: transactions.length + importReviewRows.length, uncategorized, incompleteTransfers, totalAmount };
  }, [importReviewRows.length, transactions]);

  function getForm(transaction: Transaction) {
    return forms[transaction.id] ?? buildInitialForm(transaction);
  }

  function getQuery(transactionId: number, field: string, fallback: string) {
    return formQueries[transactionId]?.[field] ?? fallback;
  }

  function updateForm(transactionId: number, patch: Partial<ReviewFormState>) {
    const transaction = transactions.find((item) => item.id === transactionId);
    if (!transaction) return;
    setForms((prev) => ({
      ...prev,
      [transactionId]: {
        ...(prev[transactionId] ?? buildInitialForm(transaction)),
        ...patch,
      },
    }));
  }

  function updateQuery(transactionId: number, field: string, value: string) {
    setFormQueries((prev) => ({
      ...prev,
      [transactionId]: {
        ...(prev[transactionId] ?? {}),
        [field]: value,
      },
    }));
  }

  function handleOperationChange(transaction: Transaction, value: TransactionOperationType) {
    const current = getForm(transaction);
    const nextType = inferTypeByOperation(value, current.type);
    updateForm(transaction.id, {
      operation_type: value,
      type: nextType,
      category_id: shouldShowCategory(value) ? current.category_id : '',
      target_account_id: isTransfer(value) ? current.target_account_id : '',
    });
    updateQuery(transaction.id, 'operation_type', getOperationLabel(value));
  }

  function openSplit(transaction: Transaction) {
    setSplitTransactionId(transaction.id);
    const half = Number(transaction.amount) / 2;
    setSplitRows([
      { category_id: '', category_query: '', amount: Number.isFinite(half) ? half.toFixed(2) : '', description: transaction.description ?? '' },
      { category_id: '', category_query: '', amount: Number.isFinite(half) ? half.toFixed(2) : '', description: transaction.description ?? '' },
    ]);
  }

  function submitSplit(transaction: Transaction) {
    const total = splitRows.reduce((acc, row) => acc + Number(row.amount || 0), 0);
    if (splitRows.some((row) => !row.category_id || Number(row.amount) <= 0)) {
      toast.error('Заполни категорию и сумму для каждой части');
      return;
    }
    if (Math.abs(total - Number(transaction.amount)) > 0.009) {
      toast.error('Сумма частей должна совпадать с исходной транзакцией');
      return;
    }
    splitMutation.mutate({
      id: transaction.id,
      payload: {
        items: splitRows.map((row) => ({
          category_id: Number(row.category_id),
          amount: Number(row.amount),
          description: row.description || transaction.description,
        })),
      },
    });
  }

  function handleCreateCategoryRequest(payload: { name: string; kind: CategoryKind }) {
    setPendingCategoryDraft({
      name: payload.name,
      kind: payload.kind,
      priority: defaultCategoryPriorityByKind[payload.kind],
    });
    setCategoryDialogOpen(true);
  }

  function handleCreateAccountRequest(payload: { name: string }) {
    setPendingAccountDraft({
      name: payload.name,
      currency: 'RUB',
      balance: 0,
      is_active: true,
      is_credit: false,
    });
    setAccountDialogOpen(true);
  }

  function getExactMatchedAccount(query: string) {
    const normalized = normalize(query);
    if (!normalized) return null;
    return accounts.find((account) => normalize(account.name) === normalized) ?? null;
  }

  function getExactMatchedCategory(query: string) {
    const normalized = normalize(query);
    if (!normalized) return null;
    return categories.find((category) => normalize(category.name) === normalized) ?? null;
  }

  if (accountsQuery.isLoading || categoriesQuery.isLoading || transactionsQuery.isLoading || importReviewQueueQuery.isLoading) {
    return <LoadingState title="Собираем очередь на проверку..." />;
  }
  if (accountsQuery.isError || categoriesQuery.isError || transactionsQuery.isError || importReviewQueueQuery.isError) {
    return <ErrorState title="Не удалось открыть review" description="Проверь доступность API и повтори попытку." />;
  }
  if (!transactions.length && !importReviewRows.length) {
    return (
      <PageShell title="Проверка" description="Здесь остаются только спорные операции, которые система не смогла уверенно классифицировать.">
        <EmptyState title="Очередь review пуста" description="Все операции либо уже автоматически классифицированы, либо подтверждены вручную." />
      </PageShell>
    );
  }

  return (
    <PageShell title="Проверка" description="Подтверждай только незнакомые операции. Всё знакомое система должна разбирать сама.">
      <AccountDialog
        open={accountDialogOpen}
        mode="create"
        initialValues={pendingAccountDraft}
        isSubmitting={createAccountMutation.isPending}
        onClose={() => setAccountDialogOpen(false)}
        onSubmit={(values) => createAccountMutation.mutate(values)}
      />

      <CategoryDialog
        open={categoryDialogOpen}
        mode="create"
        initialValues={pendingCategoryDraft}
        isSubmitting={createCategoryMutation.isPending}
        onClose={() => setCategoryDialogOpen(false)}
        onSubmit={(values) => createCategoryMutation.mutate(values)}
      />

      <div className="grid gap-4 md:grid-cols-4">
        <StatCard label="Ожидают проверки" value={stats.total} hint="Текущая очередь" icon={<ShieldAlert className="size-5" />} />
        <StatCard label="Без категории" value={stats.uncategorized} hint="Обычно это новые мерчанты" icon={<ShieldAlert className="size-5" />} />
        <StatCard label="Переводы без счёта" value={stats.incompleteTransfers} hint="Нужно выбрать счёт поступления" icon={<ShieldAlert className="size-5" />} />
        <StatCard label="Сумма очереди" value={<MoneyAmount value={stats.totalAmount} showSign className="text-2xl lg:text-3xl" />} hint="Нетто по операциям" icon={<CheckCircle2 className="size-5" />} />
      </div>

      <Card className="rounded-2xl bg-white p-5 shadow-soft">
        <div className="mb-4 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">Очередь ручной проверки</h2>
            <p className="text-sm text-slate-500">Редактирование встроено прямо в карточку. Подтверждение сразу сохраняет изменения.</p>
          </div>
          <p className="text-sm text-slate-500">Для смешанных чеков используй кнопку «Разбить по категориям».</p>
        </div>


<div className="space-y-4">
  {importReviewRows.length ? (
    <div className="space-y-3 rounded-2xl border border-amber-200 bg-amber-50/50 p-4">
      <div>
        <h3 className="text-base font-semibold text-slate-950">Импорт: требует проверки</h3>
        <p className="text-sm text-slate-500">Эти строки не импортированы в журнал. Они ждут отдельной обработки в очереди импорта.</p>
      </div>
      {importReviewRows.map((row) => {
        const operationType = String(row.normalized_data.operation_type ?? 'regular') as TransactionOperationType;
        const type = String(row.normalized_data.type ?? 'expense') as TransactionKind;
        const amount = formatImportAmount(row);
        const accountName = accounts.find((item) => item.id === Number(row.normalized_data.account_id ?? 0))?.name;
        const targetAccountName = accounts.find((item) => item.id === Number(row.normalized_data.target_account_id ?? 0))?.name;
        const categoryName = categories.find((item) => item.id === Number(row.normalized_data.category_id ?? 0))?.name;
        return (
          <div key={`import-${row.id}`} className="rounded-2xl border border-amber-200 bg-white p-4 shadow-soft">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0 flex-1 space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge tone="warning">Требует проверки</StatusBadge>
                  <StatusBadge>{getOperationLabel(operationType)}</StatusBadge>
                  <StatusBadge tone="info">{row.filename}</StatusBadge>
                  <StatusBadge tone="neutral">Строка {row.row_index}</StatusBadge>
                </div>
                <div className="text-sm text-slate-700">
                  <div className="font-medium text-slate-950">{String(row.normalized_data.description ?? 'Без описания')}</div>
                  <div className="mt-1 text-slate-500">
                    {accountName ? `Счёт: ${accountName}` : 'Счёт не определён'}
                    {categoryName ? ` • Категория: ${categoryName}` : ''}
                    {targetAccountName ? ` • Счёт получателя: ${targetAccountName}` : ''}
                  </div>
                </div>
                {row.issues.length ? (
                  <ul className="list-disc pl-5 text-sm text-amber-700">
                    {row.issues.map((issue) => (
                      <li key={issue}>{issue}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
              <div className="shrink-0">
                <MoneyAmount value={amount} currency={String(row.normalized_data.currency ?? 'RUB')} showSign tone={amount < 0 ? 'expense' : 'income'} className="text-xl" />
              </div>
            </div>
          </div>
        );
      })}
    </div>
  ) : null}

  {transactions.map((transaction) => {

            const form = getForm(transaction);
            const category = categories.find((item) => item.id === transaction.category_id);
            const priority = transaction.category_priority ?? category?.priority ?? null;
            const signedAmount = transaction.type === 'expense' ? -Number(transaction.amount) : Number(transaction.amount);
            const title = transaction.description || category?.name || getOperationLabel(transaction.operation_type);
            const splitOpen = splitTransactionId === transaction.id;
            const confirmPayload = buildPayload(form, transaction.currency);
            const currentCategoryItems = categoryItems.filter((item) => {
              if (form.operation_type === 'refund') {
                const source = categories.find((categoryItem) => String(categoryItem.id) === item.value);
                return source?.kind === 'expense';
              }
              const source = categories.find((categoryItem) => String(categoryItem.id) === item.value);
              return source?.kind === form.type;
            });

            return (
              <Card key={transaction.id} className="relative overflow-visible p-5 lg:p-6">
                <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0 flex-1 space-y-4">
                    <div className="flex items-start gap-4">
                      <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-700">
                        <ArrowRightLeft className="size-5" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-3">
                          {category ? <div className="flex size-7 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-700"><CategoryIcon iconName={category.icon_name} className="size-4" /></div> : null}
                          <h3 className="truncate text-base font-semibold text-slate-950">{title}</h3>
                        </div>

                        <div className="mt-3 flex flex-wrap gap-2">
                          <StatusBadge tone={transaction.type === 'income' ? 'income' : 'expense'}>{transactionTypeLabels[transaction.type]}</StatusBadge>
                          <StatusBadge>{getOperationLabel(transaction.operation_type)}</StatusBadge>
                          {priority ? <StatusBadge tone={getPriorityTone(priority)}>{priorityLabels[priority]}</StatusBadge> : null}
                          {transaction.needs_review ? <StatusBadge tone="warning">Требует проверки</StatusBadge> : null}
                          {!transaction.affects_analytics ? <StatusBadge tone="info">Не входит в аналитику</StatusBadge> : null}
                        </div>
                      </div>
                    </div>
                    <div className="relative z-20 grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4 md:grid-cols-2 xl:grid-cols-4 overflow-visible">
                      <SearchSelect
                        id={`operation-${transaction.id}`}
                        label="Тип"
                        placeholder="Начни вводить..."
                        widthClassName="w-full"
                        query={getQuery(transaction.id, 'operation_type', getOperationLabel(form.operation_type))}
                        setQuery={(value) => updateQuery(transaction.id, 'operation_type', value)}
                        items={operationItems}
                        selectedValue={form.operation_type}
                        onSelect={(item) => handleOperationChange(transaction, item.value as TransactionOperationType)}
                        showAllOnFocus
                      />

                      <SearchSelect
                        id={`account-${transaction.id}`}
                        label={isTransfer(form.operation_type) ? 'Счёт отправления' : 'Счёт'}
                        placeholder="Начни вводить..."
                        widthClassName="w-full"
                        query={getQuery(transaction.id, 'account_id', accountItems.find((item) => item.value === form.account_id)?.label ?? '')}
                        setQuery={(value) => updateQuery(transaction.id, 'account_id', value)}
                        items={accountItems}
                        selectedValue={form.account_id}
                        onSelect={(item) => {
                          updateForm(transaction.id, { account_id: item.value });
                          updateQuery(transaction.id, 'account_id', item.label);
                        }}
                        showAllOnFocus
                        createAction={{
                          visible: Boolean(getQuery(transaction.id, 'account_id', '').trim()) && !getExactMatchedAccount(getQuery(transaction.id, 'account_id', '')),
                          label: 'Создать счёт',
                          onClick: () => handleCreateAccountRequest({ name: getQuery(transaction.id, 'account_id', '').trim() || 'Новый счёт' }),
                        }}
                      />

                      {isTransfer(form.operation_type) ? (
                        <SearchSelect
                          id={`target-account-${transaction.id}`}
                          label="Счёт поступления"
                          placeholder="Начни вводить..."
                          widthClassName="w-full"
                          query={getQuery(transaction.id, 'target_account_id', accountItems.find((item) => item.value === form.target_account_id)?.label ?? '')}
                          setQuery={(value) => updateQuery(transaction.id, 'target_account_id', value)}
                          items={accountItems.filter((item) => item.value !== form.account_id)}
                          selectedValue={form.target_account_id}
                          onSelect={(item) => {
                            updateForm(transaction.id, { target_account_id: item.value });
                            updateQuery(transaction.id, 'target_account_id', item.label);
                          }}
                          showAllOnFocus
                          createAction={{
                            visible: Boolean(getQuery(transaction.id, 'target_account_id', '').trim()) && !getExactMatchedAccount(getQuery(transaction.id, 'target_account_id', '')),
                            label: 'Создать счёт',
                            onClick: () => handleCreateAccountRequest({ name: getQuery(transaction.id, 'target_account_id', '').trim() || 'Новый счёт' }),
                          }}
                        />
                      ) : shouldShowCategory(form.operation_type) ? (
                        <SearchSelect
                          id={`category-${transaction.id}`}
                          label="Категория"
                          placeholder="Начни вводить..."
                          widthClassName="w-full"
                          query={getQuery(transaction.id, 'category_id', currentCategoryItems.find((item) => item.value === form.category_id)?.label ?? '')}
                          setQuery={(value) => updateQuery(transaction.id, 'category_id', value)}
                          items={currentCategoryItems}
                          selectedValue={form.category_id}
                          onSelect={(item) => {
                            updateForm(transaction.id, { category_id: item.value });
                            updateQuery(transaction.id, 'category_id', item.label);
                          }}
                          showAllOnFocus
                          createAction={{
                            visible: Boolean(getQuery(transaction.id, 'category_id', '').trim()) && !getExactMatchedCategory(getQuery(transaction.id, 'category_id', '')),
                            label: 'Создать категорию',
                            onClick: () => handleCreateCategoryRequest({
                              name: getQuery(transaction.id, 'category_id', '').trim() || 'Новая категория',
                              kind: form.operation_type === 'refund' ? 'expense' : form.type,
                            }),
                          }}
                        />
                      ) : (
                        <div className="rounded-xl border border-dashed border-slate-200 bg-white px-3 py-2 text-sm text-slate-500">
                          <div className="mb-1 font-medium text-slate-700">Категория</div>
                          <div>Для этого типа не используется</div>
                        </div>
                      )}

                      <div className="rounded-xl border border-dashed border-slate-200 bg-white px-3 py-2 text-sm text-slate-500">
                        <div className="mb-1 font-medium text-slate-700">Дата</div>
                        <div>{formatDateTime(transaction.transaction_date)}</div>
                      </div>
                    </div>
                  </div>

                  <div className="flex shrink-0 flex-col gap-3 lg:items-end">
                    <MoneyAmount
                      value={signedAmount}
                      currency={transaction.currency}
                      tone={signedAmount < 0 ? 'expense' : 'income'}
                      showSign
                      className="text-xl lg:text-2xl"
                    />

                    <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                      {transaction.operation_type === 'regular' && isExpenseLike(transaction.operation_type, transaction.type) ? (
                        <Button variant="secondary" onClick={() => openSplit(transaction)}>
                          Разбить по категориям
                        </Button>
                      ) : null}
                      <Button
                        onClick={() => confirmMutation.mutate({ id: transaction.id, payload: confirmPayload })}
                        disabled={confirmMutation.isPending || !canConfirm(form)}
                      >
                        Подтвердить
                      </Button>
                      {delayedDelete.isPending(transaction.id) ? (
                        <Button
                          variant="secondary"
                          size="icon"
                          onClick={() => delayedDelete.cancelDelete(transaction.id)}
                          disabled={deletingId === transaction.id}
                          aria-label={deletingId === transaction.id ? 'Транзакция удаляется' : 'Отменить удаление транзакции'}
                          title={deletingId === transaction.id ? 'Удаляем...' : 'Отменить удаление'}
                        >
                          <RotateCcw className="size-4" />
                        </Button>
                      ) : (
                        <Button
                          variant="danger"
                          size="icon"
                          onClick={() => delayedDelete.scheduleDelete(transaction.id, () => deleteMutation.mutate(transaction.id))}
                          disabled={deletingId === transaction.id}
                          aria-label={deletingId === transaction.id ? 'Удаляем транзакцию' : 'Удалить транзакцию'}
                          title={deletingId === transaction.id ? 'Удаляем...' : 'Удалить'}
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      )}
                    </div>
                  </div>
                </div>

                {splitOpen ? (
                  <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
                    <div className="mb-3 flex items-center justify-between gap-2">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-900">Разбивка по категориям</h3>
                        <p className="text-xs text-slate-500">Сумма частей должна совпасть с исходной суммой {Number(transaction.amount).toFixed(2)}.</p>
                      </div>
                      <Button variant="secondary" onClick={() => setSplitRows((prev) => [...prev, { ...EMPTY_SPLIT_ROW, description: transaction.description ?? '' }])}>
                        <Plus className="size-4" />
                        Добавить строку
                      </Button>
                    </div>

                    <div className="space-y-3">
                      {splitRows.map((row, index) => (
                        <div key={`${transaction.id}-${index}`} className="grid gap-3 md:grid-cols-[1.2fr_10rem_1fr_auto]">
                          <SearchSelect
                            id={`split-category-${transaction.id}-${index}`}
                            label={index === 0 ? 'Категория' : ' '}
                            placeholder="Начни вводить..."
                            widthClassName="w-full"
                            query={row.category_query}
                            setQuery={(value) => setSplitRows((prev) => prev.map((item, itemIndex) => itemIndex === index ? { ...item, category_query: value, category_id: '' } : item))}
                            items={expenseCategories
                              .slice()
                              .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
                              .map((item) => ({ value: String(item.id), label: item.name, searchText: `${item.name} expense`, badge: 'Расход', badgeClassName: 'text-rose-600' }))}
                            selectedValue={row.category_id}
                            onSelect={(item) => setSplitRows((prev) => prev.map((current, itemIndex) => itemIndex === index ? { ...current, category_id: item.value, category_query: item.label } : current))}
                            showAllOnFocus
                            createAction={{
                              visible: Boolean(row.category_query.trim()) && !expenseCategories.find((item) => normalize(item.name) === normalize(row.category_query)),
                              label: 'Создать категорию',
                              onClick: () => handleCreateCategoryRequest({ name: row.category_query.trim() || 'Новая категория', kind: 'expense' }),
                            }}
                          />
                          <div>
                            <div className="mb-2 block text-sm font-medium text-slate-700">{index === 0 ? 'Сумма' : ' '}</div>
                            <Input
                              type="number"
                              step="0.01"
                              value={row.amount}
                              onChange={(event) => setSplitRows((prev) => prev.map((item, itemIndex) => itemIndex === index ? { ...item, amount: event.target.value } : item))}
                            />
                          </div>
                          <div>
                            <div className="mb-2 block text-sm font-medium text-slate-700">{index === 0 ? 'Описание части' : ' '}</div>
                            <Input
                              placeholder="Описание части"
                              value={row.description}
                              onChange={(event) => setSplitRows((prev) => prev.map((item, itemIndex) => itemIndex === index ? { ...item, description: event.target.value } : item))}
                            />
                          </div>
                          <div className="flex items-end">
                            <Button
                              variant="danger"
                              disabled={splitRows.length <= 2}
                              onClick={() => setSplitRows((prev) => prev.filter((_, itemIndex) => itemIndex !== index))}
                            >
                              <Trash2 className="size-4" />
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>

                    <div className="mt-4 flex flex-wrap justify-end gap-2">
                      <Button variant="secondary" onClick={() => setSplitTransactionId(null)}>
                        Отмена
                      </Button>
                      <Button onClick={() => submitSplit(transaction)} disabled={splitMutation.isPending}>
                        {splitMutation.isPending ? 'Сохраняем...' : 'Сохранить разбивку'}
                      </Button>
                    </div>
                  </div>
                ) : null}
              </Card>
            );
          })}
        </div>
      </Card>
    </PageShell>
  );
}
