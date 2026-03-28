'use client';

import type { Account } from '@/types/account';
import { AccountCard } from '@/components/accounts/account-card';

export function AccountsList({
  accounts,
  onEdit,
  onDelete,
  onCancelDelete,
  deletingId,
  pendingDeleteIds,
}: {
  accounts: Account[];
  onEdit: (account: Account) => void;
  onDelete: (account: Account) => void;
  onCancelDelete: (accountId: number) => void;
  deletingId?: number | null;
  pendingDeleteIds?: number[];
}) {
  const pendingSet = new Set(pendingDeleteIds ?? []);

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      {accounts.map((account) => (
        <AccountCard
          key={account.id}
          account={account}
          onEdit={onEdit}
          onDelete={onDelete}
          onCancelDelete={onCancelDelete}
          isDeletePending={pendingSet.has(account.id)}
          isDeleting={deletingId === account.id}
        />
      ))}
    </div>
  );
}
