import { apiClient } from '@/lib/api/client';

export type BankSupportRequestStatus = 'pending' | 'in_review' | 'added' | 'rejected';

export type BankSupportRequest = {
  id: number;
  bank_id: number | null;
  bank_name: string;
  note: string | null;
  status: BankSupportRequestStatus;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
};

export function createBankSupportRequest(payload: {
  bank_id?: number | null;
  bank_name: string;
  note?: string | null;
}) {
  return apiClient<BankSupportRequest>('/bank-support/request', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function listBankSupportRequests() {
  return apiClient<BankSupportRequest[]>('/bank-support/requests');
}
