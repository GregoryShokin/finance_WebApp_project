import { apiClient } from '@/lib/api/client';

export interface InstallmentDetail {
  description: string;
  monthly_payment: number;
  remaining_months: number;
}

export interface InstallmentAnnotation {
  description: string;
  category_name: string | null;
  monthly_payment: number;
  original_amount: number;
  remaining_amount: number;
  started_this_month: boolean;
}

export interface CategoryExpense {
  category_id: number | null;
  category_name: string;
  amount: number;
  is_regular: boolean;
  installment_details: InstallmentDetail[] | null;
}

export interface InstallmentAccountSummary {
  account_name: string;
  total_debt: number;
  monthly_payment: number | null;
  has_purchase_details: boolean;
}

export interface ExpenseAnalytics {
  total_expenses: number;
  regular_expenses: number;
  irregular_expenses: number;
  categories: CategoryExpense[];
  installment_annotations: InstallmentAnnotation[];
  new_installment_obligations: number;
}

export async function getExpenseAnalytics(year: number, month: number): Promise<ExpenseAnalytics> {
  return apiClient<ExpenseAnalytics>(`/analytics/expenses?year=${year}&month=${month}`);
}
