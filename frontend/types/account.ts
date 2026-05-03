export type AccountType =
  | 'main'             // обычный дебетовый
  | 'cash'             // наличный счёт (без банка)
  | 'marketplace'      // маркетплейсовый кошелёк
  | 'loan'             // потребительский кредит
  | 'credit_card'      // кредитная карта
  | 'installment_card' // карта рассрочки
  | 'broker'           // брокерский счёт
  | 'savings'          // вклад (срочный, с датами и капитализацией)
  | 'savings_account'  // накопительный счёт (бессрочный, только ставка)
  | 'currency';        // валютный счёт

export type Bank = {
  id: number;
  name: string;
  code: string;
  bik: string | null;
  is_popular: boolean;
};

export type Account = {
  id: number;
  user_id: number;
  bank_id: number;
  bank: Bank | null;
  name: string;
  currency: string;
  balance: string | number;
  is_active: boolean;
  // Spec §13 (v1.20): account closure state. is_closed=true → hidden from
  // active lists by default; visible only with include_closed=true.
  is_closed?: boolean;
  closed_at?: string | null;
  account_type: AccountType;
  is_credit: boolean;
  credit_limit?: string | number | null;
  credit_limit_original?: string | number | null;
  credit_current_amount?: string | number | null;
  credit_interest_rate?: string | number | null;
  deposit_interest_rate?: string | number | null;
  deposit_open_date?: string | null;
  deposit_close_date?: string | null;
  deposit_capitalization_period?: 'daily' | 'monthly' | 'quarterly' | 'yearly' | null;
  credit_term_remaining?: number | null;
  monthly_payment?: string | number | null;
  contract_number?: string | null;
  statement_account_number?: string | null;
  last_transaction_date: string | null;
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
  bank_id?: number | null;
  credit_limit_original?: number | null;
  credit_current_amount?: number | null;
  credit_interest_rate?: number | null;
  deposit_interest_rate?: number | null;
  deposit_open_date?: string | null;
  deposit_close_date?: string | null;
  deposit_capitalization_period?: 'daily' | 'monthly' | 'quarterly' | 'yearly' | null;
  credit_term_remaining?: number | null;
  monthly_payment?: number | null;
  contract_number?: string | null;
  statement_account_number?: string | null;
};

export type UpdateAccountPayload = Partial<CreateAccountPayload>;
