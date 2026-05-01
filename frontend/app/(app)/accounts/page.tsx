'use client';

import { useMemo, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Landmark, Pencil, PlusCircle, Trash2, Wallet, WalletCards } from 'lucide-react';
import { toast } from 'sonner';
import { AccountDialog } from '@/components/accounts/account-dialog';
import { DepositCard } from '@/components/accounts/deposit-card';
import { AccountsList } from '@/components/accounts/accounts-list';
import { RepaymentStrategies } from '@/components/accounts/repayment-strategies';
import { PageShell } from '@/components/layout/page-shell';
import { MoneyAmount } from '@/components/shared/money-amount';
import { StatCard } from '@/components/shared/stat-card';
import { EmptyState, ErrorState, LoadingState } from '@/components/states/page-state';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { createAccount, deleteAccount, getAccounts, updateAccount } from '@/lib/api/accounts';
import { createRealAsset, deleteRealAsset, getRealAssets, updateRealAsset } from '@/lib/api/real-assets';
import { getTransactions } from '@/lib/api/transactions';
import { formatMoney } from '@/lib/utils/format';
import { cn } from '@/lib/utils/cn';
import { useDelayedDelete } from '@/hooks/use-delayed-delete';
import type { Account, CreateAccountPayload } from '@/types/account';
import type { RealAsset, RealAssetPayload, RealAssetType } from '@/types/real-asset';
import type { Transaction } from '@/types/transaction';

const ASSET_TYPE_LABELS: Record<RealAssetType, string> = {
  real_estate: 'Недвижимость',
  car: 'Автомобиль',
  other: 'Прочее',
};

const ASSET_TYPE_OPTIONS: RealAssetType[] = ['real_estate', 'car', 'other'];

const EMPTY_ASSET: RealAssetPayload = {
  asset_type: 'real_estate',
  name: '',
  estimated_value: 0,
  linked_account_id: null,
};

function calcCreditDebt(account: Account) {
  return Math.abs(Number(account.balance ?? 0));
}

function RealAssetForm({
  initial,
  creditAccounts,
  onSave,
  onCancel,
  isSaving,
}: {
  initial: RealAssetPayload;
  creditAccounts: Account[];
  onSave: (data: RealAssetPayload) => void;
  onCancel: () => void;
  isSaving: boolean;
}) {
  const [form, setForm] = useState<RealAssetPayload>(initial);

  function setField<K extends keyof RealAssetPayload>(key: K, value: RealAssetPayload[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form.name.trim()) {
      toast.error('Введите название имущества');
      return;
    }
    if (form.estimated_value < 0) {
      toast.error('Стоимость не может быть отрицательной');
      return;
    }
    onSave(form);
  }

  return (
    <form onSubmit={handleSubmit} className="surface-muted space-y-3 rounded-2xl p-4">
      {/* На <md (планшет в портретной 768px) — стек, на md+ — три колонки.
          На sm:grid-cols-3 (старое) поля по 200px давали тесно и текст не
          помещался в Select. */}
      <div className="grid gap-3 md:grid-cols-3">
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-500">Тип</label>
          <Select
            value={form.asset_type}
            onChange={(event) => setField('asset_type', event.target.value as RealAssetType)}
            disabled={isSaving}
          >
            {ASSET_TYPE_OPTIONS.map((type) => (
              <option key={type} value={type}>
                {ASSET_TYPE_LABELS[type]}
              </option>
            ))}
          </Select>
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-slate-500">Название</label>
          <Input
            value={form.name}
            onChange={(event) => setField('name', event.target.value)}
            placeholder="Квартира на Ленина"
            disabled={isSaving}
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-slate-500">Оценочная стоимость, ₽</label>
          <Input
            type="number"
            min={0}
            step="any"
            value={form.estimated_value || ''}
            onChange={(event) => setField('estimated_value', parseFloat(event.target.value) || 0)}
            placeholder="5 000 000"
            disabled={isSaving}
          />
        </div>
      </div>

      {creditAccounts.length > 0 ? (
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-500">Привязанный кредит</label>
          <Select
            value={form.linked_account_id ?? ''}
            onChange={(event) => setField('linked_account_id', event.target.value ? Number(event.target.value) : null)}
            disabled={isSaving}
          >
            <option value="">— не привязан —</option>
            {creditAccounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name}
              </option>
            ))}
          </Select>
        </div>
      ) : null}

      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={isSaving}>
          <Check className="size-3.5" />
          Сохранить
        </Button>
        <Button type="button" variant="secondary" size="sm" onClick={onCancel} disabled={isSaving}>
          Отмена
        </Button>
      </div>
    </form>
  );
}

function PropertyList({
  assets,
  accounts,
  onEdit,
  onDelete,
  isDeleting,
}: {
  assets: RealAsset[];
  accounts: Account[];
  onEdit: (asset: RealAsset) => void;
  onDelete: (assetId: number) => void;
  isDeleting: boolean;
}) {
  if (assets.length === 0) {
    return null;
  }

  return (
    <Card className="divide-y divide-slate-100">
      {assets.map((asset) => {
        const linkedAccount = asset.linked_account_id
          ? accounts.find((account) => account.id === asset.linked_account_id)
          : null;
        const debt = linkedAccount ? calcCreditDebt(linkedAccount) : 0;
        const netValue = Number(asset.estimated_value) - debt;

        return (
          <div key={asset.id} className="px-5 py-4">
            <div className="flex items-center gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">
                    {ASSET_TYPE_LABELS[asset.asset_type as RealAssetType] ?? asset.asset_type}
                  </span>
                  <p className="truncate text-sm font-medium text-slate-900">{asset.name}</p>
                </div>
                {linkedAccount ? (
                  <p className="mt-1.5 text-xs text-slate-500">
                    Кредит: <span className="font-medium text-slate-700">{linkedAccount.name}</span>
                    {' · '}остаток долга:{' '}
                    <span className="font-medium text-rose-600 tabular-nums">{formatMoney(debt)}</span>
                    {' · '}чистая стоимость:{' '}
                    <span className="font-medium text-emerald-700 tabular-nums">{formatMoney(netValue)}</span>
                  </p>
                ) : null}
              </div>

              <p className="shrink-0 text-sm font-semibold text-slate-900 tabular-nums">
                {formatMoney(Number(asset.estimated_value))}
              </p>

              <div className="flex shrink-0 gap-1.5">
                <Button variant="ghost" size="icon" onClick={() => onEdit(asset)} aria-label="Редактировать">
                  <Pencil className="size-4" />
                </Button>
                <Button
                  variant="danger"
                  size="icon"
                  onClick={() => onDelete(asset.id)}
                  disabled={isDeleting}
                  aria-label="Удалить"
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            </div>
          </div>
        );
      })}

      {assets.length > 1 ? (
        <div className="flex items-center justify-between px-5 py-3">
          <p className="text-sm font-medium text-slate-500">Итого</p>
          <p className="text-sm font-semibold text-slate-950 tabular-nums">
            {formatMoney(assets.reduce((sum, asset) => sum + Number(asset.estimated_value), 0))}
          </p>
        </div>
      ) : null}
    </Card>
  );
}

export default function AccountsPage() {
  const queryClient = useQueryClient();
  const delayedDelete = useDelayedDelete();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingAccount, setEditingAccount] = useState<Account | null>(null);
  const [dialogInitialValues, setDialogInitialValues] = useState<Partial<CreateAccountPayload> | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<'accounts' | 'credits' | 'deposits' | 'property'>('accounts');
  const [assetForm, setAssetForm] = useState<{ id?: number; initial: RealAssetPayload } | null>(null);

  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: getAccounts,
  });

  const transactionsQuery = useQuery({
    queryKey: ['transactions'],
    queryFn: () => getTransactions({}),
  });

  const realAssetsQuery = useQuery({
    queryKey: ['real-assets'],
    queryFn: getRealAssets,
  });

  const createMutation = useMutation({
    mutationFn: createAccount,
    onSuccess: () => {
      toast.success('Счёт создан');
      setDialogOpen(false);
      setEditingAccount(null);
      setDialogInitialValues(null);
      queryClient.invalidateQueries({ queryKey: ['accounts'] });
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось создать счёт'),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: CreateAccountPayload }) => updateAccount(id, payload),
    onSuccess: () => {
      toast.success('Счёт обновлён');
      setDialogOpen(false);
      setEditingAccount(null);
      setDialogInitialValues(null);
      queryClient.invalidateQueries({ queryKey: ['accounts'] });
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось обновить счёт'),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteAccount,
    onSuccess: () => {
      toast.success('Счёт удалён');
      queryClient.invalidateQueries({ queryKey: ['accounts'] });
      setDeletingId(null);
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Не удалось удалить счёт');
      setDeletingId(null);
    },
  });

  const createAssetMutation = useMutation({
    mutationFn: createRealAsset,
    onSuccess: () => {
      toast.success('Имущество добавлено');
      queryClient.invalidateQueries({ queryKey: ['real-assets'] });
    },
    onError: () => toast.error('Не удалось добавить имущество'),
  });

  const updateAssetMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<RealAssetPayload> }) => updateRealAsset(id, data),
    onSuccess: () => {
      toast.success('Имущество обновлено');
      queryClient.invalidateQueries({ queryKey: ['real-assets'] });
    },
    onError: () => toast.error('Не удалось обновить имущество'),
  });

  const deleteAssetMutation = useMutation({
    mutationFn: deleteRealAsset,
    onSuccess: () => {
      toast.success('Имущество удалено');
      queryClient.invalidateQueries({ queryKey: ['real-assets'] });
    },
    onError: () => toast.error('Не удалось удалить имущество'),
  });

  const accounts = accountsQuery.data ?? [];
  const transactions: Transaction[] = transactionsQuery.data ?? [];
  const realAssets = realAssetsQuery.data ?? [];
  const creditAccounts = accounts.filter((account) => account.account_type === 'loan');

  const accountItems = useMemo(
    () => accounts.filter((account) => account.account_type !== 'loan' && account.account_type !== 'savings'),
    [accounts],
  );

  const creditItems = useMemo(
    () => accounts.filter((account) => account.account_type === 'loan'),
    [accounts],
  );
  const depositItems = useMemo(
    () => accounts.filter((account) => account.account_type === 'savings'),
    [accounts],
  );

  const accountStats = useMemo(() => {
    const activeCount = accountItems.filter((account) => account.is_active).length;
    const totalBalance = accountItems.reduce((sum, account) => sum + Number(account.balance), 0);

    return {
      total: accountItems.length,
      active: activeCount,
      inactive: accountItems.length - activeCount,
      totalBalance,
    };
  }, [accountItems]);

  const creditStats = useMemo(() => {
    const activeCredits = creditItems.filter((account) => account.is_active);
    return {
      total: creditItems.length,
      totalDebt: creditItems.reduce((sum, account) => sum + Math.abs(Number(account.balance)), 0),
      monthlyPayment: activeCredits.reduce((sum, account) => sum + Number(account.monthly_payment ?? 0), 0),
      inactive: creditItems.length - activeCredits.length,
    };
  }, [creditItems]);

  const totalRepaymentBudget = useMemo(() => {
    return creditItems
      .filter((account) => account.is_active && Math.abs(Number(account.balance)) > 0)
      .reduce((sum, account) => {
        // After Phase 1: credit_payment abolished.
        // Interest = expense/regular with credit_account_id.
        // Body = transfer with credit_account_id set (not a plain card top-up).
        // Sum all payments for the most recent month found.
        const allPayments = transactions
          .filter((tx) => {
            const isInterest = tx.type === 'expense' && tx.operation_type === 'regular' && tx.credit_account_id === account.id;
            const isBody = tx.operation_type === 'transfer' && tx.target_account_id === account.id && tx.credit_account_id != null;
            return isInterest || isBody;
          })
          .sort((a, b) => new Date(b.transaction_date).getTime() - new Date(a.transaction_date).getTime());

        if (allPayments.length > 0) {
          // Find the most recent month and sum all its payments (interest + body)
          const latestDate = new Date(allPayments[0].transaction_date);
          const latestMonth = `${latestDate.getFullYear()}-${latestDate.getMonth()}`;
          const monthTotal = allPayments
            .filter((tx) => {
              const d = new Date(tx.transaction_date);
              return `${d.getFullYear()}-${d.getMonth()}` === latestMonth;
            })
            .reduce((s, tx) => s + Number(tx.amount), 0);
          if (monthTotal > 0) return sum + monthTotal;
        }

        if (Number(account.monthly_payment ?? 0) > 0) {
          return sum + Number(account.monthly_payment);
        }

        return sum + Math.max(1000, Math.abs(Number(account.balance)) * 0.02);
      }, 0);
  }, [creditItems, transactions]);

  const propertyStats = useMemo(
    () => ({
      total: realAssets.length,
      totalValue: realAssets.reduce((sum, asset) => sum + Number(asset.estimated_value), 0),
    }),
    [realAssets],
  );
  const depositStats = useMemo(
    () => ({
      total: depositItems.length,
      totalBalance: depositItems.reduce((sum, account) => sum + Math.abs(Number(account.balance)), 0),
    }),
    [depositItems],
  );

  function openCreateDialog(initialValues: Partial<CreateAccountPayload>) {
    setEditingAccount(null);
    setDialogInitialValues(initialValues);
    setDialogOpen(true);
  }

  function openEditDialog(account: Account) {
    setEditingAccount(account);
    setDialogInitialValues(null);
    setDialogOpen(true);
  }

  function handleDialogSubmit(values: CreateAccountPayload) {
    if (editingAccount) {
      updateMutation.mutate({ id: editingAccount.id, payload: values });
      return;
    }

    createMutation.mutate(values);
  }

  function handleDelete(account: Account) {
    delayedDelete.scheduleDelete(account.id, () => {
      setDeletingId(account.id);
      deleteMutation.mutate(account.id);
    });
  }

  function renderStats() {
    if (activeTab === 'credits') {
      return (
        <div className="grid gap-4 md:grid-cols-3">
          <StatCard
            label="Кредитов"
            value={creditStats.total}
            hint={`Неактивных: ${creditStats.inactive}`}
            icon={<Wallet className="size-5" />}
          />
          <StatCard
            label="Суммарный долг"
            value={<MoneyAmount value={creditStats.totalDebt} tone="expense" className="text-2xl lg:text-3xl" />}
            hint="Сумма остатков по всем кредитам"
            icon={<WalletCards className="size-5" />}
          />
          <StatCard
            label="Платёж/мес"
            value={<MoneyAmount value={creditStats.monthlyPayment} className="text-2xl lg:text-3xl" />}
            hint="Сумма monthly payment по активным кредитам"
            icon={<Landmark className="size-5" />}
          />
        </div>
      );
    }

    if (activeTab === 'property') {
      return (
        <div className="grid gap-4 md:grid-cols-3">
          <StatCard
            label="Объектов"
            value={propertyStats.total}
            hint="Недвижимость, авто и прочее имущество"
            icon={<Wallet className="size-5" />}
          />
          <Card className="p-5 lg:p-6" aria-hidden="true" />
          <StatCard
            label="Суммарная стоимость"
            value={<MoneyAmount value={propertyStats.totalValue} className="text-2xl lg:text-3xl" />}
            hint="Оценочная стоимость всех объектов"
            icon={<Landmark className="size-5" />}
          />
        </div>
      );
    }

    if (activeTab === 'deposits') {
      return (
        <div className="grid gap-4 md:grid-cols-2">
          <StatCard
            label="Вкладов"
            value={depositStats.total}
            hint="Активные и завершённые депозитные счета"
            icon={<Wallet className="size-5" />}
          />
          <StatCard
            label="На вкладах"
            value={<MoneyAmount value={depositStats.totalBalance} tone="income" className="text-2xl lg:text-3xl" />}
            hint="Суммарный баланс по всем вкладам"
            icon={<Landmark className="size-5" />}
          />
        </div>
      );
    }

    return (
      <div className="grid gap-4 md:grid-cols-3">
        <StatCard
          label="Всего счетов"
          value={accountStats.total}
          hint="Все счета и карты кроме кредитов"
          icon={<Wallet className="size-5" />}
        />
        <StatCard
          label="Активные"
          value={accountStats.active}
          hint={`Неактивных: ${accountStats.inactive}`}
          icon={<WalletCards className="size-5" />}
        />
        <StatCard
          label="Суммарный баланс"
          value={<MoneyAmount value={accountStats.totalBalance} className="text-2xl lg:text-3xl" />}
          hint="Итог по счетам и картам"
          icon={<Landmark className="size-5" />}
        />
      </div>
    );
  }

  function renderPropertyContent() {
    return (
      <div className="space-y-4">
        <div className="mb-4 flex justify-end">
          <Button onClick={() => setAssetForm({ initial: EMPTY_ASSET })} disabled={!!assetForm}>
            <PlusCircle className="size-4" />
            Добавить имущество
          </Button>
        </div>

        {assetForm ? (
          <RealAssetForm
            initial={assetForm.initial}
            creditAccounts={creditAccounts}
            isSaving={createAssetMutation.isPending || updateAssetMutation.isPending}
            onCancel={() => setAssetForm(null)}
            onSave={(data) => {
              if (assetForm.id !== undefined) {
                updateAssetMutation.mutate({ id: assetForm.id, data });
              } else {
                createAssetMutation.mutate(data);
              }
              setAssetForm(null);
            }}
          />
        ) : null}

        {realAssetsQuery.isLoading ? (
          <LoadingState title="Загружаем имущество..." description="Подтягиваем список объектов и оценочную стоимость." />
        ) : null}

        {realAssetsQuery.isError ? (
          <ErrorState title="Не удалось загрузить имущество" description="Проверь доступность backend API и повтори попытку." />
        ) : null}

        {!realAssetsQuery.isLoading && !realAssetsQuery.isError && realAssets.length === 0 ? (
          <EmptyState
            title="Имущество не добавлено"
            description="Добавь недвижимость, автомобиль или другое имущество для учёта чистого капитала."
          />
        ) : null}

        {!realAssetsQuery.isLoading && !realAssetsQuery.isError && realAssets.length > 0 ? (
          <PropertyList
            assets={realAssets}
            accounts={accounts}
            isDeleting={deleteAssetMutation.isPending}
            onEdit={(asset) =>
              setAssetForm({
                id: asset.id,
                initial: {
                  asset_type: asset.asset_type as RealAssetType,
                  name: asset.name,
                  estimated_value: Number(asset.estimated_value),
                  linked_account_id: asset.linked_account_id ?? null,
                },
              })
            }
            onDelete={(assetId) => deleteAssetMutation.mutate(assetId)}
          />
        ) : null}
      </div>
    );
  }

  function renderTabContent() {
    if (activeTab === 'property') {
      return renderPropertyContent();
    }

    if (accountsQuery.isLoading) {
      return <LoadingState title="Загружаем счета..." description="Подтягиваем баланс и статус каждого счёта." />;
    }

    if (accountsQuery.isError) {
      return <ErrorState title="Не удалось загрузить счета" description="Проверь доступность backend API и повтори попытку." />;
    }

    if (activeTab === 'deposits') {
      return (
        <div className="space-y-4">
          <div className="mb-4 flex justify-end">
            <Button onClick={() => openCreateDialog({ account_type: 'savings', is_credit: false })}>
              <PlusCircle className="size-4" />
              Добавить вклад
            </Button>
          </div>

          {depositItems.length === 0 ? (
            <EmptyState
              title="Вкладов пока нет"
              description="Добавь первый вклад для отслеживания процентного дохода."
            />
          ) : (
            <div className="space-y-4">
              {depositItems.map((account) => (
                <DepositCard
                  key={account.id}
                  account={account}
                  onEdit={openEditDialog}
                  onDelete={handleDelete}
                />
              ))}

              <div className="flex items-center justify-between rounded-3xl border border-white/60 bg-white/85 px-5 py-4 shadow-soft">
                <p className="text-sm font-medium text-slate-500">Итого на вкладах</p>
                <p className="text-lg font-semibold text-emerald-700 tabular-nums">
                  {formatMoney(depositStats.totalBalance)}
                </p>
              </div>
            </div>
          )}
        </div>
      );
    }

    if (activeTab === 'credits') {
      return (
        <div className="space-y-4">
          <div className="mb-4 flex justify-end">
            <Button
              onClick={() => openCreateDialog({ account_type: 'loan', is_credit: true })}
            >
              <PlusCircle className="size-4" />
              Добавить кредит
            </Button>
          </div>

          {creditItems.length === 0 ? (
            <EmptyState
              title="Кредитов пока нет"
              description="Добавь ипотеку или кредит чтобы отслеживать остаток и график погашения."
            />
          ) : (
            <div className="space-y-6">
              <AccountsList
                accounts={creditItems}
                onEdit={openEditDialog}
                onDelete={handleDelete}
                onCancelDelete={delayedDelete.cancelDelete}
                deletingId={deletingId}
                pendingDeleteIds={Object.keys(delayedDelete.pendingIds).map(Number)}
                transactions={transactions}
              />
              <RepaymentStrategies accounts={creditItems} totalBudget={totalRepaymentBudget} />
            </div>
          )}
        </div>
      );
    }

    return (
      <div className="space-y-4">
        <div className="mb-4 flex justify-end">
          <Button onClick={() => openCreateDialog({ account_type: 'main' })}>
            <PlusCircle className="size-4" />
            Добавить счёт или карту
          </Button>
        </div>

        {accountItems.length === 0 ? (
          <EmptyState
            title="Счетов пока нет"
            description="Создай первый счёт, чтобы привязывать к нему транзакции и видеть баланс в личном кабинете."
          />
        ) : (
          <AccountsList
            accounts={accountItems}
            onEdit={openEditDialog}
            onDelete={handleDelete}
            onCancelDelete={delayedDelete.cancelDelete}
            deletingId={deletingId}
            pendingDeleteIds={Object.keys(delayedDelete.pendingIds).map(Number)}
            transactions={transactions}
          />
        )}
      </div>
    );
  }

  return (
    <PageShell
      title="Активы"
      description="Счета, кредиты и имущество — полная картина твоих активов и обязательств."
    >
      {renderStats()}

      <div className="flex gap-1 rounded-xl bg-slate-100 p-1">
        {[
          { key: 'accounts', label: 'Счета и карты' },
          { key: 'credits', label: 'Кредиты' },
          { key: 'deposits', label: 'Вклады' },
          { key: 'property', label: 'Имущество' },
        ].map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key as typeof activeTab)}
            className={cn(
              'flex-1 rounded-lg px-4 py-2 text-sm font-medium transition-all',
              activeTab === tab.key ? 'bg-white text-slate-950 shadow-sm' : 'text-slate-500 hover:text-slate-700',
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {renderTabContent()}

      <AccountDialog
        open={dialogOpen}
        mode={editingAccount ? 'edit' : 'create'}
        account={editingAccount}
        initialValues={editingAccount ? null : dialogInitialValues}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        onClose={() => {
          setDialogOpen(false);
          setEditingAccount(null);
          setDialogInitialValues(null);
        }}
        onSubmit={handleDialogSubmit}
      />
    </PageShell>
  );
}
