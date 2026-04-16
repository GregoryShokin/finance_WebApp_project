import { apiClient } from '@/lib/api/client';
import type { Account, CreateAccountPayload, UpdateAccountPayload } from '@/types/account';

export function getAccounts() {
  return apiClient<Account[]>('/accounts');
}

export function createAccount(payload: CreateAccountPayload) {
  return apiClient<Account>('/accounts', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateAccount(accountId: number, payload: UpdateAccountPayload) {
  return apiClient<Account>(`/accounts/${accountId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export function deleteAccount(accountId: number) {
  return apiClient<void>(`/accounts/${accountId}`, {
    method: 'DELETE',
  });
}

export function adjustAccountBalance(accountId: number, targetBalance: number, comment?: string) {
  return apiClient<{ ok: boolean }>(`/accounts/${accountId}/adjust`, {
    method: 'POST',
    body: JSON.stringify({ target_balance: targetBalance, comment: comment ?? null }),
  });
}
