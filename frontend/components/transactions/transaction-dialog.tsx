'use client';

import { Dialog } from '@/components/ui/dialog';
import { TransactionForm } from '@/components/transactions/transaction-form';
import type { Account } from '@/types/account';
import type { Category } from '@/types/category';
import type { DebtPartner } from '@/types/debt-partner';
import type { GoalWithProgress } from '@/types/goal';
import type { CreateTransactionPayload, Transaction } from '@/types/transaction';

export function TransactionDialog({
  open,
  mode,
  transaction,
  accounts,
  categories,
  debtPartners = [],
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
  debtPartners?: DebtPartner[];
  goals?: GoalWithProgress[];
  isSubmitting?: boolean;
  onClose: () => void;
  onSubmit: (values: CreateTransactionPayload, installment?: { description: string; term_months: number; monthly_payment: number; original_amount: number; start_date: string; existingPurchaseId?: number | null } | null) => void;
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
        debtPartners={debtPartners}
        goals={goals}
        isSubmitting={isSubmitting}
        onSubmit={onSubmit}
        onCancel={onClose}
      />
    </Dialog>
  );
}
