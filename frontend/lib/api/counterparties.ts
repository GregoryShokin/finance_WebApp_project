import { apiClient } from '@/lib/api/client';
import type { Counterparty, CreateCounterpartyPayload } from '@/types/counterparty';

export function getCounterparties() {
  return apiClient<Counterparty[]>('/counterparties');
}

export function createCounterparty(payload: CreateCounterpartyPayload) {
  return apiClient<Counterparty>('/counterparties', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateCounterparty(
  counterpartyId: number,
  payload: { name?: string },
) {
  return apiClient<Counterparty>(`/counterparties/${counterpartyId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function deleteCounterparty(counterpartyId: number) {
  return apiClient<void>(`/counterparties/${counterpartyId}`, {
    method: 'DELETE',
  });
}
