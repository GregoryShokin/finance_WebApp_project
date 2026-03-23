"use client";

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, ChevronUp, PencilLine, PlusCircle, ReceiptText, Search, ShieldAlert, Trash2, TrendingDown } from 'lucide-react';
import { toast } from 'sonner';
import { PageShell } from '@/components/layout/page-shell';
import { ErrorState, EmptyState, LoadingState } from '@/components/states/page-state';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { AccountDialog } from '@/components/accounts/account-dialog';
import { CategoryDialog } from '@/components/categories/category-dialog';
import { getAccounts, createAccount } from '@/lib/api/accounts';
import { getCategories, createCategory } from '@/lib/api/categories';
import { createTransaction, deleteTransaction, deleteTransactionsByPeriod, getTransactions, updateTransaction } from '@/lib/api/transactions';
import { TransactionsList } from '@/components/transactions/transactions-list';
import { TransactionFilters } from '@/components/transactions/transaction-filters';
import { TransactionForm } from '@/components/transactions/transaction-form';
import type { CreateAccountPayload } from '@/types/account';
import type { CategoryKind, CategoryPriority, CreateCategoryPayload } from '@/types/category';
import type { CreateTransactionPayload, Transaction, TransactionKind, TransactionOperationType } from '@/types/transaction';
import { MoneyAmount } from '@/components/shared/money-amount';
import { StatCard } from '@/components/shared/stat-card';
import { operationTypeLabels, transactionTypeLabels } from '@/components/transactions/constants';

type FiltersState = {
  search: string;
  account_id: string;
  category_id: string;
  category_priority: 'all' | CategoryPriority;
  type: 'all' | TransactionKind;
  operation_type: 'all' | TransactionOperationType;
  date_from: string;
  date_to: string;
  min_amount: string;
  max_amount: string;
  needs_review: 'all' | 'true' | 'false';
};

const defaultFilters: FiltersState = {
  search: '',
  account_id: '',
  category_id: '',
  category_priority: 'all',
  type: 'all',
  operation_type: 'all',
  date_from: '',
  date_to: '',
  min_amount: '',
  max_amount: '',
  needs_review: 'all',
};

const defaultCategoryPriorityByKind: Record<CategoryKind, CategoryPriority> = {
  expense: 'expense_secondary',
  income: 'income_active',
};

const reviewLabels = {
  true: 'требует проверки',
  false: 'подтверждена',
} as const;

function normalizeSearchValue(value: unknown) {
  return String(value ?? '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
}

function toIsoStart(date: string) {
  return new Date(`${date}T00:00:00`).toISOString();
}

function toIsoEnd(date: string) {
  return new Date(`${date}T23:59:59`).toISOString();
}

export default function TransactionsPage() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<FiltersState>(defaultFilters);
  const [formOpen, setFormOpen] = useState(false);
  const [filtersCollapsed, setFiltersCollapsed] = useState(true);
  const [editingTransaction, setEditingTransaction] = useState<Transaction | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const [accountDialogOpen, setAccountDialogOpen] = useState(false);
  const [categoryDialogOpen, setCategoryDialogOpen] = useState(false);
  const [pendingAccountDraft, setPendingAccountDraft] = useState<Partial<CreateAccountPayload> | null>(null);
  const [pendingCategoryDraft, setPendingCategoryDraft] = useState<Partial<CreateCategoryPayload> | null>(null);

  const accountsQuery = useQuery({ queryKey: ['accounts'], queryFn: getAccounts });
  const categoriesQuery = useQuery({ queryKey: ['categories', 'all-for-transactions'], queryFn: () => getCategories() });

  const transactionsQuery = useQuery({
    queryKey: ['transactions', filters],
    queryFn: () =>
      getTransactions({
        account_id: filters.account_id ? Number(filters.account_id) : undefined,
        category_id: filters.category_id ? Number(filters.category_id) : undefined,
        category_priority: filters.category_priority,
        type: filters.type,
        operation_type: filters.operation_type,
        date_from: filters.date_from ? toIsoStart(filters.date_from) : undefined,
        date_to: filters.date_to ? toIsoEnd(filters.date_to) : undefined,
        min_amount: filters.min_amount ? Number(filters.min_amount) : undefined,
        max_amount: filters.max_amount ? Number(filters.max_amount) : undefined,
        needs_review: filters.needs_review === 'all' ? 'all' : filters.needs_review === 'true',
      }),
    enabled: accountsQuery.isSuccess && categoriesQuery.isSuccess,
  });

  const invalidateTransactionData = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['transactions'] }),
      queryClient.invalidateQueries({ queryKey: ['accounts'] }),
      queryClient.invalidateQueries({ queryKey: ['categories'] }),
    ]);
    await Promise.all([
      queryClient.refetchQueries({ queryKey: ['transactions'] }),
      queryClient.refetchQueries({ queryKey: ['accounts'] }),
    ]);
  };

  const createMutation = useMutation({
    mutationFn: createTransaction,
    onSuccess: async () => {
      toast.success('Транзакция создана');
      setFormOpen(false);
      await invalidateTransactionData();
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось создать транзакцию'),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: CreateTransactionPayload }) => updateTransaction(id, payload),
    onSuccess: async () => {
      toast.success('Транзакция обновлена');
      setFormOpen(false);
      setEditingTransaction(null);
      await invalidateTransactionData();
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось обновить транзакцию'),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteTransaction,
    onSuccess: async () => {
      toast.success('Транзакция удалена');
      setDeletingId(null);
      await invalidateTransactionData();
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Не удалось удалить транзакцию');
      setDeletingId(null);
    },
  });

  const deletePeriodMutation = useMutation({
    mutationFn: deleteTransactionsByPeriod,
    onSuccess: async (result) => {
      toast.success(result.deleted_count > 0 ? `Удалено транзакций: ${result.deleted_count}` : 'За период транзакции не найдены');
      await invalidateTransactionData();
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось удалить транзакции за период'),
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

  const filteredTransactions = useMemo(() => {
    const search = normalizeSearchValue(filters.search);
    const list = transactionsQuery.data ?? [];
    if (!search) return list;

    const accountsById = new Map((accountsQuery.data ?? []).map((item) => [item.id, item]));
    const categoriesById = new Map((categoriesQuery.data ?? []).map((item) => [item.id, item]));

    return list.filter((item) => {
      const account = accountsById.get(item.account_id);
      const targetAccount = item.target_account_id ? accountsById.get(item.target_account_id) : null;
      const category = item.category_id ? categoriesById.get(item.category_id) : null;
      const title = item.description || category?.name || operationTypeLabels[item.operation_type];
      const haystack = normalizeSearchValue([
        title,
        item.description,
        item.normalized_description,
        category?.name,
        account?.name,
        targetAccount?.name,
        transactionTypeLabels[item.type],
        operationTypeLabels[item.operation_type],
        item.currency,
        item.amount,
        item.transaction_date,
        item.needs_review ? reviewLabels.true : reviewLabels.false,
      ].join(' '));

      return haystack.includes(search);
    });
  }, [transactionsQuery.data, accountsQuery.data, categoriesQuery.data, filters.search]);

  const stats = useMemo(() => {
    const list = filteredTransactions;
    const income = list.filter((item) => item.type === 'income' && item.affects_analytics).reduce((acc, item) => acc + Number(item.amount), 0);
    const expense = list.filter((item) => item.type === 'expense' && item.affects_analytics).reduce((acc, item) => acc + Number(item.amount), 0);
    const review = list.filter((item) => item.needs_review).length;
    return { total: list.length, income, expense, review };
  }, [filteredTransactions]);

  function openCreateForm() {
    setEditingTransaction(null);
    setFormOpen(true);
  }

  function openEditForm(transaction: Transaction) {
    setFormOpen(false);
    setEditingTransaction(transaction);
  }

  function closeForm() {
    setFormOpen(false);
    setEditingTransaction(null);
  }

  function handleFormSubmit(values: CreateTransactionPayload) {
    if (editingTransaction) {
      updateMutation.mutate({ id: editingTransaction.id, payload: values });
      return;
    }
    createMutation.mutate(values);
  }

  function handleDelete(transaction: Transaction) {
    const confirmed = window.confirm('Удалить эту транзакцию?');
    if (!confirmed) return;
    setDeletingId(transaction.id);
    deleteMutation.mutate(transaction.id);
  }

  function handleDeletePeriod() {
    if (!filters.date_from || !filters.date_to) {
      toast.error('Для удаления за период укажи даты "с" и "по" в фильтрах.');
      return;
    }

    const confirmed = window.confirm('Удалить все транзакции за выбранный период? Это действие нельзя отменить.');
    if (!confirmed) return;

    deletePeriodMutation.mutate({
      date_from: toIsoStart(filters.date_from),
      date_to: toIsoEnd(filters.date_to),
      account_id: filters.account_id ? Number(filters.account_id) : undefined,
    });
  }

  function handleCreateCategoryRequest(payload: { name: string; kind: CategoryKind }) {
    setPendingCategoryDraft({
      name: payload.name,
      kind: payload.kind,
      priority: defaultCategoryPriorityByKind[payload.kind],
      color: '#22c55e',
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

  return (
    <PageShell title="Транзакции" description="Учитывай обычные операции, переводы, инвестиции, долги и кредиты без искажения аналитики.">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Операций найдено" value={stats.total} hint="С учётом текущих фильтров" icon={<ReceiptText className="size-5" />} />
        <StatCard label="Доходы в аналитике" value={<MoneyAmount value={stats.income} tone="income" className="text-2xl lg:text-3xl" />} hint="Только влияющие на аналитику" icon={<PlusCircle className="size-5" />} />
        <StatCard label="Расходы в аналитике" value={<MoneyAmount value={stats.expense} tone="expense" className="text-2xl lg:text-3xl" />} hint="Только влияющие на аналитику" icon={<TrendingDown className="size-5" />} />
        <StatCard label="Требуют проверки" value={stats.review} hint="Полезно для review flow" icon={<ShieldAlert className="size-5" />} />
      </div>

      <Card className="rounded-2xl bg-white p-4 shadow-soft">
        <div className="mb-3 flex flex-col gap-1">
          <h2 className="text-sm font-semibold text-slate-900">Общий поиск</h2>
          <p className="text-xs text-slate-500">Введи слово или фразу, чтобы найти совпадения по названию, описанию, счёту, категории и другим полям.</p>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
          <input
            className="flex h-11 w-full rounded-xl border border-slate-200 bg-white pl-10 pr-3 text-sm text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-slate-300 focus:ring-2 focus:ring-slate-200"
            placeholder="Например: зарплата, Тинькофф, такси"
            value={filters.search}
            onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))}
          />
        </div>
      </Card>

      <TransactionFilters
        value={filters}
        accounts={accountsQuery.data ?? []}
        categories={categoriesQuery.data ?? []}
        collapsed={filtersCollapsed}
        onToggle={() => setFiltersCollapsed((prev) => !prev)}
        onChange={setFilters}
      />

      <div className="flex flex-wrap gap-3">
        <Button onClick={() => (formOpen && !editingTransaction ? closeForm() : openCreateForm())}>
          {formOpen && !editingTransaction ? <ChevronUp className="size-4" /> : <PlusCircle className="size-4" />}
          {formOpen && !editingTransaction ? 'Свернуть блок добавления' : 'Добавить транзакцию'}
        </Button>
        <Button variant="danger" onClick={handleDeletePeriod} disabled={deletePeriodMutation.isPending || !filters.date_from || !filters.date_to}>
          <Trash2 className="size-4" />
          {deletePeriodMutation.isPending ? 'Удаляем...' : 'Удалить за период'}
        </Button>
      </div>

      {formOpen ? (
        <div>
          <Card className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft lg:p-6">
            <div className="mb-5 flex flex-col gap-3 border-b border-slate-200 pb-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-950">Новая транзакция</h2>
                <p className="mt-1 text-sm text-slate-500">Форма добавления открыта на странице. Здесь же можно быстро добавить новый счёт или категорию.</p>
              </div>
              <Button variant="secondary" onClick={closeForm}>
                <ChevronUp className="size-4" />
                Скрыть блок
              </Button>
            </div>

            <TransactionForm
              initialData={null}
              accounts={accountsQuery.data ?? []}
              categories={categoriesQuery.data ?? []}
              isSubmitting={createMutation.isPending}
              onCancel={closeForm}
              onSubmit={handleFormSubmit}
              onCreateAccountRequest={handleCreateAccountRequest}
              onCreateCategoryRequest={handleCreateCategoryRequest}
            />
          </Card>
        </div>
      ) : null}

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

      {transactionsQuery.isLoading || accountsQuery.isLoading || categoriesQuery.isLoading ? <LoadingState title="Загружаем транзакции..." description="Собираем операции, счета и категории." /> : null}
      {transactionsQuery.isError || accountsQuery.isError || categoriesQuery.isError ? <ErrorState title="Не удалось загрузить транзакции" description="Проверь backend API и повтори попытку." /> : null}

      {!transactionsQuery.isLoading && !transactionsQuery.isError && !accountsQuery.isLoading && !categoriesQuery.isLoading && filteredTransactions.length === 0 ? (
        <EmptyState title="Транзакции не найдены" description="Создай первую операцию или ослабь фильтры." />
      ) : null}

      {!transactionsQuery.isLoading && !transactionsQuery.isError && filteredTransactions.length > 0 ? (
        <TransactionsList
          transactions={filteredTransactions}
          accounts={accountsQuery.data ?? []}
          categories={categoriesQuery.data ?? []}
          onEdit={openEditForm}
          onDelete={handleDelete}
          deletingId={deletingId}
          editingTransaction={editingTransaction}
          isSubmittingEdit={updateMutation.isPending}
          onSubmitEdit={handleFormSubmit}
          onCancelEdit={closeForm}
          onCreateAccountRequest={handleCreateAccountRequest}
          onCreateCategoryRequest={handleCreateCategoryRequest}
        />
      ) : null}
    </PageShell>
  );
}
