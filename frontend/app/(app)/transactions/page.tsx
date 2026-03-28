"use client";

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronUp, PlusCircle, ReceiptText, Search, ShieldAlert, Trash2, TrendingDown } from 'lucide-react';
import { toast } from 'sonner';
import { PageShell } from '@/components/layout/page-shell';
import { ErrorState, EmptyState, LoadingState } from '@/components/states/page-state';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { AccountDialog } from '@/components/accounts/account-dialog';
import { CategoryDialog } from '@/components/categories/category-dialog';
import { CounterpartyDialog } from '@/components/counterparties/counterparty-dialog';
import { getAccounts, createAccount } from '@/lib/api/accounts';
import { getCategories, createCategory } from '@/lib/api/categories';
import { getCounterparties, createCounterparty, deleteCounterparty } from '@/lib/api/counterparties';
import { createTransaction, deleteTransaction, deleteTransactionsByPeriod, getTransactions, updateTransaction } from '@/lib/api/transactions';
import { TransactionsList } from '@/components/transactions/transactions-list';
import { TransactionFilters } from '@/components/transactions/transaction-filters';
import { TransactionForm } from '@/components/transactions/transaction-form';
import type { CreateAccountPayload } from '@/types/account';
import type { CreateCounterpartyPayload } from '@/types/counterparty';
import type { CategoryKind, CategoryPriority, CreateCategoryPayload } from '@/types/category';
import type { CreateTransactionPayload, Transaction, TransactionKind, TransactionOperationType } from '@/types/transaction';
import { MoneyAmount } from '@/components/shared/money-amount';
import { StatCard } from '@/components/shared/stat-card';
import { operationTypeLabels, transactionTypeLabels } from '@/components/transactions/constants';
import { useDelayedDelete } from '@/hooks/use-delayed-delete';


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

const reviewLabels = { true: 'требует проверки', false: 'подтверждена' } as const;

function normalizeSearchValue(value: unknown) {
  return String(value ?? '').toLowerCase().replace(/\s+/g, ' ').trim();
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
  const delayedDelete = useDelayedDelete();

  const [accountDialogOpen, setAccountDialogOpen] = useState(false);
  const [categoryDialogOpen, setCategoryDialogOpen] = useState(false);
  const [counterpartyDialogOpen, setCounterpartyDialogOpen] = useState(false);
  const [pendingAccountDraft, setPendingAccountDraft] = useState<Partial<CreateAccountPayload> | null>(null);
  const [pendingCategoryDraft, setPendingCategoryDraft] = useState<Partial<CreateCategoryPayload> | null>(null);
  const [pendingCounterpartyDraft, setPendingCounterpartyDraft] = useState<Partial<CreateCounterpartyPayload> | null>(null);

  const accountsQuery = useQuery({ queryKey: ['accounts'], queryFn: getAccounts });
  const categoriesQuery = useQuery({ queryKey: ['categories', 'all-for-transactions'], queryFn: () => getCategories() });
  const counterpartiesQuery = useQuery({ queryKey: ['counterparties'], queryFn: getCounterparties });
  const transactionsQuery = useQuery({
    queryKey: ['transactions', filters],
    queryFn: () => getTransactions({
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
    enabled: accountsQuery.isSuccess && categoriesQuery.isSuccess && counterpartiesQuery.isSuccess,
  });

  const invalidateData = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['transactions'] }),
      queryClient.invalidateQueries({ queryKey: ['accounts'] }),
      queryClient.invalidateQueries({ queryKey: ['categories'] }),
      queryClient.invalidateQueries({ queryKey: ['counterparties'] }),
    ]);
  };

  const createMutation = useMutation({ mutationFn: createTransaction, onSuccess: async () => { toast.success('Транзакция создана'); setFormOpen(false); await invalidateData(); }, onError: (error: Error) => toast.error(error.message || 'Не удалось создать транзакцию') });
  const updateMutation = useMutation({ mutationFn: ({ id, payload }: { id: number; payload: CreateTransactionPayload }) => updateTransaction(id, payload), onSuccess: async () => { toast.success('Транзакция обновлена'); setEditingTransaction(null); await invalidateData(); }, onError: (error: Error) => toast.error(error.message || 'Не удалось обновить транзакцию') });
  const deleteMutation = useMutation({ mutationFn: deleteTransaction, onSuccess: async () => { toast.success('Транзакция удалена'); setDeletingId(null); await invalidateData(); }, onError: (error: Error) => { toast.error(error.message || 'Не удалось удалить транзакцию'); setDeletingId(null); } });
  const deletePeriodMutation = useMutation({ mutationFn: deleteTransactionsByPeriod, onSuccess: async (result) => { toast.success(result.deleted_count > 0 ? `Удалено транзакций: ${result.deleted_count}` : 'За период транзакции не найдены'); await invalidateData(); }, onError: (error: Error) => toast.error(error.message || 'Не удалось удалить транзакции за период') });
  const createAccountMutation = useMutation({ mutationFn: createAccount, onSuccess: async () => { toast.success('Счёт создан'); setAccountDialogOpen(false); await invalidateData(); }, onError: (error: Error) => toast.error(error.message || 'Не удалось создать счёт') });
  const createCategoryMutation = useMutation({ mutationFn: createCategory, onSuccess: async () => { toast.success('Категория создана'); setCategoryDialogOpen(false); await invalidateData(); }, onError: (error: Error) => toast.error(error.message || 'Не удалось создать категорию') });
  const createCounterpartyMutation = useMutation({ mutationFn: createCounterparty, onSuccess: async () => { toast.success('Контрагент создан'); setCounterpartyDialogOpen(false); await invalidateData(); }, onError: (error: Error) => toast.error(error.message || 'Не удалось создать контрагента') });
  const deleteCounterpartyMutation = useMutation({ mutationFn: deleteCounterparty, onSuccess: async () => { toast.success('Контрагент удалён'); await invalidateData(); }, onError: (error: Error) => toast.error(error.message || 'Не удалось удалить контрагента') });

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
      const title = item.description || item.counterparty_name || (category?.name ?? operationTypeLabels[item.operation_type]);
      const haystack = normalizeSearchValue([
        title,
        item.description,
        item.normalized_description,
        item.counterparty_name,
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
    return {
      total: list.length,
      income: list.filter((item) => item.type === 'income' && item.affects_analytics).reduce((acc, item) => acc + Number(item.amount), 0),
      expense: list.filter((item) => item.type === 'expense' && item.affects_analytics).reduce((acc, item) => acc + Number(item.amount), 0),
      review: list.filter((item) => item.needs_review).length,
    };
  }, [filteredTransactions]);

  const isLoading = accountsQuery.isLoading || categoriesQuery.isLoading || counterpartiesQuery.isLoading || transactionsQuery.isLoading;
  const isError = accountsQuery.isError || categoriesQuery.isError || counterpartiesQuery.isError || transactionsQuery.isError;

  function openCreateForm() { setEditingTransaction(null); setFormOpen(true); }
  function closeCreateForm() { setFormOpen(false); }
  function cancelEdit() { setEditingTransaction(null); }
  function handleCreateSubmit(values: CreateTransactionPayload) { createMutation.mutate(values); }
  function handleEditSubmit(values: CreateTransactionPayload) {
    if (!editingTransaction) return;
    updateMutation.mutate({ id: editingTransaction.id, payload: values });
  }
  function handleDelete(transaction: Transaction) { delayedDelete.scheduleDelete(transaction.id, () => { setDeletingId(transaction.id); deleteMutation.mutate(transaction.id); }); }
  function handleDeletePeriod() { if (!filters.date_from || !filters.date_to) return; deletePeriodMutation.mutate({ date_from: toIsoStart(filters.date_from), date_to: toIsoEnd(filters.date_to), account_id: filters.account_id ? Number(filters.account_id) : undefined }); }
  function handleCreateCategoryRequest(payload: { name: string; kind: CategoryKind }) { setPendingCategoryDraft({ name: payload.name, kind: payload.kind, priority: defaultCategoryPriorityByKind[payload.kind] }); setCategoryDialogOpen(true); }
  function handleCreateAccountRequest(payload: { name: string }) { setPendingAccountDraft({ name: payload.name, currency: 'RUB', balance: 0, is_active: true, is_credit: false }); setAccountDialogOpen(true); }
  function handleCreateCounterpartyRequest(payload: { name: string; opening_balance_kind: 'receivable' | 'payable' }) { setPendingCounterpartyDraft({ name: payload.name, opening_balance_kind: payload.opening_balance_kind, opening_balance: 0 }); setCounterpartyDialogOpen(true); }

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
          <p className="text-xs text-slate-500">Введи слово или фразу, чтобы найти совпадения по названию, описанию, счёту, категории и контрагенту.</p>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
          <input className="flex h-11 w-full rounded-xl border border-slate-200 bg-white pl-10 pr-3 text-sm text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-slate-300 focus:ring-2 focus:ring-slate-200" placeholder="Например: зарплата, Тинькофф, Иван" value={filters.search} onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))} />
        </div>
      </Card>

      <TransactionFilters value={filters} accounts={accountsQuery.data ?? []} categories={categoriesQuery.data ?? []} collapsed={filtersCollapsed} onToggle={() => setFiltersCollapsed((prev) => !prev)} onReset={() => setFilters(defaultFilters)} onChange={setFilters} />

      <div className="flex flex-wrap gap-3">
        <Button onClick={() => (formOpen ? closeCreateForm() : openCreateForm())}>
          {formOpen ? <ChevronUp className="size-4" /> : <PlusCircle className="size-4" />}
          {formOpen ? 'Свернуть блок добавления' : 'Добавить транзакцию'}
        </Button>
        <Button variant="danger" onClick={handleDeletePeriod} disabled={deletePeriodMutation.isPending || !filters.date_from || !filters.date_to}>
          <Trash2 className="size-4" />
          {deletePeriodMutation.isPending ? 'Удаляем...' : 'Удалить за период'}
        </Button>
      </div>

      {formOpen ? (
        <Card className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft lg:p-6">
          <div className="mb-5 flex flex-col gap-3 border-b border-slate-200 pb-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-950">Новая транзакция</h2>
              <p className="mt-1 text-sm text-slate-500">Здесь же можно быстро добавить новый счёт, категорию или контрагента.</p>
            </div>
            <Button variant="secondary" onClick={closeCreateForm}><ChevronUp className="size-4" />Скрыть блок</Button>
          </div>
          <TransactionForm
            initialData={null}
            accounts={accountsQuery.data ?? []}
            categories={categoriesQuery.data ?? []}
            counterparties={counterpartiesQuery.data ?? []}
            isSubmitting={createMutation.isPending || updateMutation.isPending}
            onCancel={closeCreateForm}
            onSubmit={handleCreateSubmit}
            onCreateAccountRequest={handleCreateAccountRequest}
            onCreateCategoryRequest={handleCreateCategoryRequest}
            onCreateCounterpartyRequest={handleCreateCounterpartyRequest}
            onDeleteCounterpartyRequest={(counterparty) => deleteCounterpartyMutation.mutate(counterparty.id)}
          />
        </Card>
      ) : null}

      <AccountDialog open={accountDialogOpen} mode="create" initialValues={pendingAccountDraft} isSubmitting={createAccountMutation.isPending} onClose={() => setAccountDialogOpen(false)} onSubmit={(values) => createAccountMutation.mutate(values)} />
      <CategoryDialog open={categoryDialogOpen} mode="create" initialValues={pendingCategoryDraft} isSubmitting={createCategoryMutation.isPending} onClose={() => setCategoryDialogOpen(false)} onSubmit={(values) => createCategoryMutation.mutate(values)} />
      <CounterpartyDialog open={counterpartyDialogOpen} draft={pendingCounterpartyDraft} isSubmitting={createCounterpartyMutation.isPending} onClose={() => setCounterpartyDialogOpen(false)} onSubmit={(values) => createCounterpartyMutation.mutate(values)} />

      {isLoading ? <LoadingState title="Загружаем транзакции..." description="Собираем операции, счета, категории и контрагентов." /> : null}
      {isError ? <ErrorState title="Не удалось загрузить транзакции" description="Проверь backend API и повтори попытку." /> : null}
      {!isLoading && !isError && filteredTransactions.length === 0 ? <EmptyState title="Транзакции не найдены" description="Создай первую операцию или ослабь фильтры." /> : null}
      {!isLoading && !isError && filteredTransactions.length > 0 ? (
        <TransactionsList
          transactions={filteredTransactions}
          accounts={accountsQuery.data ?? []}
          categories={categoriesQuery.data ?? []}
          counterparties={counterpartiesQuery.data ?? []}
          editingTransaction={editingTransaction}
          deletingId={deletingId}
          pendingDeleteIds={Object.keys(delayedDelete.pendingIds).map(Number)}
          isSubmittingEdit={updateMutation.isPending}
          onEdit={(transaction) => { setFormOpen(false); setEditingTransaction(transaction); }}
          onDelete={handleDelete}
          onCancelDelete={(transactionId) => delayedDelete.cancelDelete(transactionId)}
          onSubmitEdit={handleEditSubmit}
          onCancelEdit={cancelEdit}
          onCreateAccountRequest={handleCreateAccountRequest}
          onCreateCategoryRequest={handleCreateCategoryRequest}
          onCreateCounterpartyRequest={handleCreateCounterpartyRequest}
          onDeleteCounterpartyRequest={(counterparty) => deleteCounterpartyMutation.mutate(counterparty.id)}
        />
      ) : null}
    </PageShell>
  );
}
