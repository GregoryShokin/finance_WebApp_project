"use client";

import { ArrowRightLeft, CornerDownLeft, Pencil, RotateCcw, Trash2 } from 'lucide-react';
import { CategoryIcon } from '@/components/categories/category-icon';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import type { Account } from '@/types/account';
import type { Category, CategoryPriority } from '@/types/category';
import type { Transaction } from '@/types/transaction';
import { operationTypeLabels, transactionTypeLabels } from '@/components/transactions/constants';
import { formatDateTime } from '@/lib/utils/format';
import { MoneyAmount } from '@/components/shared/money-amount';
import { StatusBadge } from '@/components/shared/status-badge';

const priorityLabels: Record<CategoryPriority, string> = {
  expense_essential: 'Обязательный',
  expense_secondary: 'Второстепенный',
  expense_target: 'Имущество',
  income_active: 'Активный доход',
  income_passive: 'Пассивный доход',
};

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

export function TransactionCard({
  transaction,
  accounts,
  categories,
  onEdit,
  onDelete,
  onCancelDelete,
  isDeletePending,
  isDeleting,
  isEditing,
}: {
  transaction: Transaction;
  accounts: Account[];
  categories: Category[];
  onEdit: (transaction: Transaction) => void;
  onDelete?: (transaction: Transaction) => void;
  onCancelDelete?: (transactionId: number) => void;
  isDeletePending?: boolean;
  isDeleting?: boolean;
  isEditing?: boolean;
}) {
  const account = accounts.find((item) => item.id === transaction.account_id);
  const targetAccount = accounts.find((item) => item.id === transaction.target_account_id);
  const creditAccount = accounts.find((item) => item.id === transaction.credit_account_id);
  const category = categories.find((item) => item.id === transaction.category_id);
  const priority = transaction.category_priority ?? category?.priority ?? null;
  const isRefund = transaction.operation_type === 'refund';
  const signedAmount = isRefund ? Number(transaction.amount) : transaction.type === 'expense' ? -Number(transaction.amount) : Number(transaction.amount);
  const title = transaction.description || (isRefund && category ? `Возврат · ${category.name}` : category?.name) || operationTypeLabels[transaction.operation_type];

  return (
    <Card className={isEditing ? 'border border-slate-300 p-5 ring-2 ring-slate-200 lg:p-6' : 'p-5 lg:p-6'}>
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1 space-y-4">
          <div className="flex items-start gap-4">
            <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-700">
              {isRefund ? <CornerDownLeft className="size-5" /> : <ArrowRightLeft className="size-5" />}
            </div>
            <div className="min-w-0 flex-1 overflow-hidden">
              <div className="flex items-center gap-3">
                {category ? <div className="flex size-7 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-700"><CategoryIcon iconName={category.icon_name} className="size-4" /></div> : null}
                <h3 className="text-base font-semibold text-slate-950 break-words [overflow-wrap:anywhere]">{title}</h3>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                <StatusBadge tone={isRefund ? 'income' : transaction.type === 'income' ? 'income' : 'expense'}>
                  {isRefund ? 'Возврат' : transactionTypeLabels[transaction.type]}
                </StatusBadge>
                <StatusBadge>{operationTypeLabels[transaction.operation_type]}</StatusBadge>
                {priority ? <StatusBadge tone={getPriorityTone(priority)}>{priorityLabels[priority]}</StatusBadge> : null}
                {transaction.needs_review ? <StatusBadge tone="warning">Требует проверки</StatusBadge> : null}
                {!transaction.affects_analytics ? <StatusBadge tone="info">Не входит в аналитику</StatusBadge> : null}
              </div>
            </div>
          </div>

          <div className="grid gap-2 text-sm text-slate-500 md:grid-cols-3">
            <p className="min-w-0 break-words [overflow-wrap:anywhere]">Счёт: <span className="font-medium text-slate-700">{account?.name ?? '—'}</span></p>
            {transaction.operation_type === 'transfer' ? <p className="min-w-0 break-words [overflow-wrap:anywhere]">Поступление: <span className="font-medium text-slate-700">{targetAccount?.name ?? '—'}</span></p> : transaction.operation_type === 'credit_payment' ? <p className="min-w-0 break-words [overflow-wrap:anywhere]">Кредит: <span className="font-medium text-slate-700">{creditAccount?.name ?? '—'}</span></p> : <p className="min-w-0 break-words [overflow-wrap:anywhere]">Категория: <span className="font-medium text-slate-700">{category?.name ?? '—'}</span></p>}
            <p>Дата: <span className="font-medium text-slate-700">{formatDateTime(transaction.transaction_date)}</span></p>
            {transaction.operation_type === 'credit_disbursement' ? <p>Кредитная операция: <span className="font-medium text-slate-700">Получение кредита</span></p> : null}
            {transaction.operation_type === 'credit_payment' ? <p>Основной долг: <span className="font-medium text-slate-700">{Number(transaction.credit_principal_amount ?? 0).toLocaleString('ru-RU')} · Проценты: {Number(transaction.credit_interest_amount ?? 0).toLocaleString('ru-RU')}</span></p> : null}
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
            <Button
              variant="secondary"
              size="icon"
              onClick={() => onEdit(transaction)}
              aria-label="Изменить транзакцию"
              title="Изменить"
            >
              <Pencil className="size-4" />
            </Button>
            {onDelete ? (
              isDeletePending ? (
                <Button
                  variant="secondary"
                  size="icon"
                  onClick={() => onCancelDelete?.(transaction.id)}
                  disabled={isDeleting}
                  aria-label={isDeleting ? 'Транзакция удаляется' : 'Отменить удаление транзакции'}
                  title={isDeleting ? 'Удаляем...' : 'Отменить удаление'}
                >
                  <RotateCcw className="size-4" />
                </Button>
              ) : (
                <Button
                  variant="danger"
                  size="icon"
                  onClick={() => onDelete(transaction)}
                  disabled={isDeleting}
                  aria-label={isDeleting ? 'Удаляем транзакцию' : 'Удалить транзакцию'}
                  title={isDeleting ? 'Удаляем...' : 'Удалить'}
                >
                  <Trash2 className="size-4" />
                </Button>
              )
            ) : null}
          </div>
        </div>
      </div>
    </Card>
  );
}
