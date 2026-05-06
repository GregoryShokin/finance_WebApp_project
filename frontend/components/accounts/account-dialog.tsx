'use client';

import { Dialog } from '@/components/ui/dialog';
import { AccountForm } from '@/components/accounts/account-form';
import type { Account, AccountType, Bank, CreateAccountPayload } from '@/types/account';

export function AccountDialog({
  open,
  mode,
  account,
  initialValues,
  initialBank,
  allowedTypes,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  open: boolean;
  mode: 'create' | 'edit';
  account?: Account | null;
  initialValues?: Partial<CreateAccountPayload> | null;
  initialBank?: Bank | null;
  allowedTypes?: AccountType[];
  isSubmitting?: boolean;
  onClose: () => void;
  onSubmit: (values: CreateAccountPayload) => void;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={mode === 'create' ? 'Новый счёт' : 'Редактировать счёт'}
      description={mode === 'create' ? 'Добавь счёт, чтобы привязывать к нему транзакции и видеть общий баланс.' : 'Измени параметры счёта.'}
    >
      <AccountForm
        initialData={account}
        initialValues={initialValues}
        initialBank={initialBank}
        allowedTypes={allowedTypes}
        isSubmitting={isSubmitting}
        onSubmit={onSubmit}
        onCancel={onClose}
      />
    </Dialog>
  );
}
