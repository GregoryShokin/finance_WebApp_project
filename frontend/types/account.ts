export type Account = {
  id: number;
  user_id: number;
  name: string;
  currency: string;
  balance: string | number;
  is_active: boolean;
  is_credit: boolean;
  created_at: string;
  updated_at: string;
};

export type CreateAccountPayload = {
  name: string;
  currency: string;
  balance: number;
  is_active: boolean;
  is_credit: boolean;
};

export type UpdateAccountPayload = Partial<CreateAccountPayload>;
