export type Counterparty = {
  id: number;
  user_id: number;
  name: string;
  opening_receivable_amount: number;
  opening_payable_amount: number;
  receivable_amount: number;
  payable_amount: number;
  created_at: string;
  updated_at: string;
};

export type CreateCounterpartyPayload = {
  name: string;
  opening_balance?: number;
  opening_balance_kind?: 'receivable' | 'payable';
};
