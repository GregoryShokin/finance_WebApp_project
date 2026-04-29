import { apiClient } from '@/lib/api/client';
import type { DebtPartner, CreateDebtPartnerPayload } from '@/types/debt-partner';

export function getDebtPartners() {
  return apiClient<DebtPartner[]>('/debt-partners');
}

export function createDebtPartner(payload: CreateDebtPartnerPayload) {
  return apiClient<DebtPartner>('/debt-partners', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function deleteDebtPartner(partnerId: number) {
  return apiClient<void>(`/debt-partners/${partnerId}`, {
    method: 'DELETE',
  });
}
