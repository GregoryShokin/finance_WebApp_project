export type InstallmentPurchaseStatus = 'active' | 'completed' | 'early_closed';

export type InstallmentPurchase = {
  id: number;
  account_id: number;
  transaction_id: number | null;
  category_id: number | null;
  description: string;
  original_amount: string | number;
  remaining_amount: string | number;
  interest_rate: string | number;
  term_months: number;
  monthly_payment: string | number;
  start_date: string;
  status: InstallmentPurchaseStatus;
  created_at: string;
  updated_at: string;
};

export type CreateInstallmentPurchasePayload = {
  description: string;
  category_id?: number | null;
  transaction_id?: number | null;
  original_amount: number;
  interest_rate?: number;
  term_months: number;
  monthly_payment: number;
  start_date: string;
};

export type UpdateInstallmentPurchasePayload = {
  description?: string;
  category_id?: number | null;
  remaining_amount?: number;
  status?: InstallmentPurchaseStatus;
};

export type InstallmentPurchaseListResponse = {
  items: InstallmentPurchase[];
  warning: string | null;
};
