import { apiClient } from '@/lib/api/client';
import type {
  CreateInstallmentPurchasePayload,
  InstallmentPurchase,
  InstallmentPurchaseListResponse,
  UpdateInstallmentPurchasePayload,
} from '@/types/installment-purchase';

export function getInstallmentPurchases(accountId: number) {
  return apiClient<InstallmentPurchaseListResponse>(
    `/accounts/${accountId}/installment-purchases`,
  );
}

export function createInstallmentPurchase(
  accountId: number,
  payload: CreateInstallmentPurchasePayload,
) {
  return apiClient<InstallmentPurchase>(
    `/accounts/${accountId}/installment-purchases`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  );
}

export function getInstallmentPurchase(accountId: number, purchaseId: number) {
  return apiClient<InstallmentPurchase>(
    `/accounts/${accountId}/installment-purchases/${purchaseId}`,
  );
}

export function updateInstallmentPurchase(
  accountId: number,
  purchaseId: number,
  payload: UpdateInstallmentPurchasePayload,
) {
  return apiClient<InstallmentPurchase>(
    `/accounts/${accountId}/installment-purchases/${purchaseId}`,
    {
      method: 'PUT',
      body: JSON.stringify(payload),
    },
  );
}

export function deleteInstallmentPurchase(accountId: number, purchaseId: number) {
  return apiClient<void>(
    `/accounts/${accountId}/installment-purchases/${purchaseId}`,
    {
      method: 'DELETE',
    },
  );
}
