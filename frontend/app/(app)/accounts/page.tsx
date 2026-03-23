"use client";

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Landmark, PlusCircle, Wallet, WalletCards } from 'lucide-react';
import { toast } from 'sonner';
import { PageShell } from '@/components/layout/page-shell';
import { AccountsList } from '@/components/accounts/accounts-list';
import { AccountDialog } from '@/components/accounts/account-dialog';
import { ErrorState, EmptyState, LoadingState } from '@/components/states/page-state';
import { Button } from '@/components/ui/button';
import { createAccount, deleteAccount, getAccounts, updateAccount } from '@/lib/api/accounts';
import type { Account, CreateAccountPayload } from '@/types/account';
import { MoneyAmount } from '@/components/shared/money-amount';
import { StatCard } from '@/components/shared/stat-card';

export default function AccountsPage() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingAccount, setEditingAccount] = useState<Account | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: getAccounts,
  });

  const createMutation = useMutation({
    mutationFn: createAccount,
    onSuccess: () => {
      toast.success('Счёт создан');
      setDialogOpen(false);
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

  const totalBalance = useMemo(() => {
    return (accountsQuery.data ?? []).reduce((sum, account) => sum + Number(account.balance), 0);
  }, [accountsQuery.data]);

  const activeCount = useMemo(() => (accountsQuery.data ?? []).filter((account) => account.is_active).length, [accountsQuery.data]);
  const inactiveCount = (accountsQuery.data?.length ?? 0) - activeCount;

  function openCreateDialog() {
    setEditingAccount(null);
    setDialogOpen(true);
  }

  function openEditDialog(account: Account) {
    setEditingAccount(account);
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
    const confirmed = window.confirm(`Удалить счёт «${account.name}»?`);
    if (!confirmed) return;

    setDeletingId(account.id);
    deleteMutation.mutate(account.id);
  }

  return (
    <PageShell
      title="Счета"
      description="Управляй банковскими картами, кошельками и любыми источниками баланса в едином формате интерфейса."
      actions={
        <Button onClick={openCreateDialog}>
          <PlusCircle className="size-4" />
          Добавить счёт
        </Button>
      }
    >
      <div className="grid gap-4 md:grid-cols-3">
        <StatCard label="Всего счетов" value={accountsQuery.data?.length ?? 0} hint="Все созданные источники баланса" icon={<Wallet className="size-5" />} />
        <StatCard label="Активные" value={activeCount} hint={`Неактивных: ${inactiveCount}`} icon={<WalletCards className="size-5" />} />
        <StatCard label="Суммарный баланс" value={<MoneyAmount value={totalBalance} className="text-2xl lg:text-3xl" />} hint="Итог по всем счетам" icon={<Landmark className="size-5" />} />
      </div>

      {accountsQuery.isLoading ? <LoadingState title="Загружаем счета..." description="Подтягиваем баланс и статус каждого счёта." /> : null}

      {accountsQuery.isError ? <ErrorState title="Не удалось загрузить счета" description="Проверь доступность backend API и повтори попытку." /> : null}

      {!accountsQuery.isLoading && !accountsQuery.isError && (accountsQuery.data?.length ?? 0) === 0 ? (
        <EmptyState title="Счетов пока нет" description="Создай первый счёт, чтобы привязывать к нему транзакции и видеть баланс в личном кабинете." />
      ) : null}

      {!accountsQuery.isLoading && !accountsQuery.isError && (accountsQuery.data?.length ?? 0) > 0 ? (
        <AccountsList accounts={accountsQuery.data ?? []} onEdit={openEditDialog} onDelete={handleDelete} deletingId={deletingId} />
      ) : null}

      <AccountDialog
        open={dialogOpen}
        mode={editingAccount ? 'edit' : 'create'}
        account={editingAccount}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        onClose={() => {
          setDialogOpen(false);
          setEditingAccount(null);
        }}
        onSubmit={handleDialogSubmit}
      />
    </PageShell>
  );
}
