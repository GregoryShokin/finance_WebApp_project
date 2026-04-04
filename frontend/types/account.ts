export type AccountType = 'regular' | 'credit' | 'credit_card' | 'cash' | 'broker';

export type Account = {
  id: number;
  user_id: number;
  name: string;
  currency: string;
  balance: string | number;
  is_active: boolean;
  account_type: AccountType;
  is_credit: boolean;
  credit_limit?: string | number | null;
  credit_limit_original?: string | number | null;
  credit_current_amount?: string | number | null;
  credit_interest_rate?: string | number | null;
  credit_term_remaining?: number | null;
  monthly_payment?: string | number | null;
  created_at: string;
  updated_at: string;
};

export type CreateAccountPayload = {
  name: string;
  currency: string;
  balance: number;
  is_active: boolean;
  account_type: AccountType;
  is_credit: boolean;
  credit_limit_original?: number | null;
  credit_current_amount?: number | null;
  credit_interest_rate?: number | null;
  credit_term_remaining?: number | null;
  monthly_payment?: number | null;
};

export type UpdateAccountPayload = Partial<CreateAccountPayload>;
