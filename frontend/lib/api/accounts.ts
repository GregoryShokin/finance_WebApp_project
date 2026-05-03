import { apiClient } from '@/lib/api/client';
import type { Account, CreateAccountPayload, UpdateAccountPayload } from '@/types/account';

/**
 * Fetch user's accounts. By default closed accounts (spec §13 v1.20) are
 * excluded — pass `{ includeClosed: true }` to include them, used by the
 * accounts page «Закрытые счета» section and the moderator's
 * AccountSelector dropdown that needs closed accounts as valid targets.
 *
 * Accepts an unknown first argument so the function is compatible with
 * being passed directly as a react-query `queryFn` (which calls it with a
 * QueryFunctionContext) — only the `includeClosed` field is read.
 */
export function getAccounts(opts?: unknown) {
  const includeClosed = !!(opts && typeof opts === 'object' && 'includeClosed' in opts && (opts as { includeClosed?: boolean }).includeClosed);
  const qs = includeClosed ? '?include_closed=true' : '';
  return apiClient<Account[]>(`/accounts${qs}`);
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

/**
 * Mark an account as closed (spec §13, v1.20). Backend validates closed_at
 * is not in the future and not earlier than the latest transaction.
 */
export function closeAccount(accountId: number, closedAt: string) {
  return apiClient<Account>(`/accounts/${accountId}/close`, {
    method: 'POST',
    body: JSON.stringify({ closed_at: closedAt }),
  });
}

/**
 * Re-open a previously closed account (spec §13, v1.20).
 */
export function reopenAccount(accountId: number) {
  return apiClient<Account>(`/accounts/${accountId}/reopen`, {
    method: 'POST',
  });
}
