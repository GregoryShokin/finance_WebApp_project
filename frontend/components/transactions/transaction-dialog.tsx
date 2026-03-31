'use client';

import { Dialog } from '@/components/ui/dialog';
import { TransactionForm } from '@/components/transactions/transaction-form';
import type { Account } from '@/types/account';
import type { Category } from '@/types/category';
import type { Counterparty } from '@/types/counterparty';
import type { GoalWithProgress } from '@/types/goal';
import type { CreateTransactionPayload, Transaction } from '@/types/transaction';

export function TransactionDialog({
  open,
  mode,
  transaction,
  accounts,
  categories,
  counterparties = [],
  goals = [],
  isSubmitting,
  onClose,
  onSubmit,
}: {
  open: boolean;
  mode: 'create' | 'edit';
  transaction?: Transaction | null;
  accounts: Account[];
  categories: Category[];
  counterparties?: Counterparty[];
  goals?: GoalWithProgress[];
  isSubmitting?: boolean;
  onClose: () => void;
  onSubmit: (values: CreateTransactionPayload) => void;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={mode === 'create' ? 'Новая транзакция' : 'Редактировать транзакцию'}
      description={
        mode === 'create'
          ? 'Создай обычную операцию, перевод, инвестиционное движение или кредитную запись.'
          : 'Обнови параметры выбранной транзакции.'
      }
      size="lg"
    >
      <TransactionForm
        initialData={transaction}
        accounts={accounts}
        categories={categories}
        counterparties={counterparties}
        goals={goals}
        isSubmitting={isSubmitting}
        onSubmit={onSubmit}
        onCancel={onClose}
      />
    </Dialog>
  );
}
