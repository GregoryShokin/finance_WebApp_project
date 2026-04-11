import { apiClient } from '@/lib/api/client';
import type {
  CreateTransactionPayload,
  DeleteTransactionsByPeriodPayload,
  LargePurchaseCheck,
  Transaction,
  TransactionsQuery,
  UpdateTransactionPayload,
  SplitTransactionPayload,
} from '@/types/transaction';

export function getTransactions(query?: TransactionsQuery) {
  const params = new URLSearchParams();

  if (query?.account_id) params.set('account_id', String(query.account_id));
  if (query?.category_id) params.set('category_id', String(query.category_id));
  if (query?.category_priority && query.category_priority !== 'all') {
    params.set('category_priority', query.category_priority);
  }
  if (query?.type && query.type !== 'all') params.set('type', query.type);
  if (query?.operation_type && query.operation_type !== 'all') params.set('operation_type', query.operation_type);
  if (query?.date_from) params.set('date_from', query.date_from);
  if (query?.date_to) params.set('date_to', query.date_to);
  if (typeof query?.min_amount === 'number') params.set('min_amount', String(query.min_amount));
  if (typeof query?.max_amount === 'number') params.set('max_amount', String(query.max_amount));
  if (query?.needs_review !== undefined && query.needs_review !== 'all') {
    params.set('needs_review', String(query.needs_review));
  }

  const qs = params.toString();
  return apiClient<Transaction[]>(`/transactions${qs ? `?${qs}` : ''}`);
}

export function createTransaction(payload: CreateTransactionPayload) {
  return apiClient<Transaction>('/transactions', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateTransaction(transactionId: number, payload: UpdateTransactionPayload) {
  return apiClient<Transaction>(`/transactions/${transactionId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export function deleteTransaction(transactionId: number) {
  return apiClient<void>(`/transactions/${transactionId}`, {
    method: 'DELETE',
  });
}

export function deleteTransactionsByPeriod(payload: DeleteTransactionsByPeriodPayload) {
  return apiClient<{ deleted_count: number }>('/transactions/delete-period', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}


export function splitTransaction(transactionId: number, payload: SplitTransactionPayload) {
  return apiClient<Transaction[]>(`/transactions/${transactionId}/split`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function checkLargePurchase(amount: number) {
  return apiClient<LargePurchaseCheck>(
    `/transactions/large-purchase-check?amount=${amount}`,
  );
}
