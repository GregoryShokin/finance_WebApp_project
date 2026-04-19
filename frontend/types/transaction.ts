import type { CategoryPriority } from '@/types/category';

export type TransactionKind = 'income' | 'expense';

export type TransactionOperationType =
  | 'regular'
  | 'transfer'
  | 'investment_buy'
  | 'investment_sell'
  | 'credit_disbursement'
  | 'credit_early_repayment'
  | 'debt'
  | 'refund'
  | 'adjustment';

export type Transaction = {
  id: number;
  user_id: number;
  account_id: number;
  target_account_id: number | null;
  credit_account_id: number | null;
  goal_id: number | null;
  category_id: number | null;
  counterparty_id: number | null;
  category_priority?: CategoryPriority | null;
  is_regular: boolean;
  converted_to_installment: boolean;
  installment_term_months?: number | null;
  installment_monthly_payment?: number | null;
  installment_description?: string | null;
  amount: number;
  credit_principal_amount?: number | null;
  credit_interest_amount?: number | null;
  debt_direction?: 'lent' | 'borrowed' | 'repaid' | 'collected' | null;
  currency: string;
  type: TransactionKind;
  operation_type: TransactionOperationType;
  counterparty_name?: string | null;
  description: string | null;
  normalized_description: string | null;
  transaction_date: string;
  needs_review: boolean;
  affects_analytics: boolean;
  created_at: string;
  updated_at: string;
};

export type CreateTransactionPayload = {
  account_id: number;
  target_account_id?: number | null;
  credit_account_id?: number | null;
  goal_id?: number | null;
  category_id?: number | null;
  counterparty_id?: number | null;
  amount: number;
  credit_principal_amount?: number | null;
  credit_interest_amount?: number | null;
  debt_direction?: 'lent' | 'borrowed' | 'repaid' | 'collected' | null;
  currency: string;
  type: TransactionKind;
  operation_type: TransactionOperationType;
  description?: string | null;
  transaction_date: string;
  needs_review?: boolean;
};

export type UpdateTransactionPayload = Partial<CreateTransactionPayload>;

export type DeleteTransactionsByPeriodPayload = {
  date_from: string;
  date_to: string;
  account_id?: number;
};

export type TransactionsQuery = {
  account_id?: number;
  category_id?: number;
  category_priority?: CategoryPriority | 'all';
  type?: TransactionKind | 'all';
  operation_type?: TransactionOperationType | 'all';
  date_from?: string;
  date_to?: string;
  min_amount?: number;
  max_amount?: number;
  needs_review?: boolean | 'all';
};

export type SplitTransactionPayload = {
  items: Array<{
    category_id: number;
    amount: number;
    description?: string | null;
  }>;
};
