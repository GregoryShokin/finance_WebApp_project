import type { TransactionKind, TransactionOperationType } from '@/types/transaction';

export const transactionTypeLabels: Record<TransactionKind, string> = {
  income: 'Доход',
  expense: 'Расход',
};

export const operationTypeLabels: Record<TransactionOperationType, string> = {
  regular: 'Обычный',
  transfer: 'Перевод между счетами',
  investment_buy: 'Инвестиционный: покупка',
  investment_sell: 'Инвестиционный: продажа',
  credit_disbursement: 'Тело кредита: получение',
  credit_payment: 'Тело кредита: погашение',
  credit_interest: 'Проценты по кредиту',
  debt: 'Долг',
  refund: 'Возврат',
  adjustment: 'Корректировка',
};

export function getOperationOptionsByKind(kind?: string | null) {
  if (!kind) {
    return [
      { value: 'regular', label: 'Обычный' },
      { value: 'refund', label: 'Возврат' },
      { value: 'adjustment', label: 'Корректировка' },
      { value: 'adjustment', label: 'Корректировка' },
      { value: 'investment_buy', label: 'Инвестиции (покупка)' },
      { value: 'investment_sell', label: 'Инвестиции (продажа)' },
      { value: 'credit_disbursement', label: 'Тело кредита' },
      { value: 'debt', label: 'Долг' },
    ];
  }

  if (kind === 'income') {
    return [
      { value: 'regular', label: 'Обычный' },
      { value: 'investment_sell', label: 'Инвестиции (продажа)' },
      { value: 'credit_disbursement', label: 'Тело кредита' },
      { value: 'debt', label: 'Долг' },
    ];
  }

  if (kind === 'expense') {
    return [
      { value: 'regular', label: 'Обычный' },
      { value: 'refund', label: 'Возврат' },
      { value: 'adjustment', label: 'Корректировка' },
      { value: 'investment_buy', label: 'Инвестиции (покупка)' },
      { value: 'debt', label: 'Долг' },
    ];
  }

  return [];
}
