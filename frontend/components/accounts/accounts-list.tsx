'use client';

import type { Account } from '@/types/account';
import { AccountCard } from '@/components/accounts/account-card';

export function AccountsList({
  accounts,
  onEdit,
  onDelete,
  deletingId,
}: {
  accounts: Account[];
  onEdit: (account: Account) => void;
  onDelete: (account: Account) => void;
  deletingId?: number | null;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      {accounts.map((account) => (
        <AccountCard
          key={account.id}
          account={account}
          onEdit={onEdit}
          onDelete={onDelete}
          isDeleting={deletingId === account.id}
        />
      ))}
    </div>
  );
}
