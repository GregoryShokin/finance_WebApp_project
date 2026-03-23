export type CategoryKind = 'income' | 'expense';

export type CategoryPriority =
  | 'expense_essential'
  | 'expense_secondary'
  | 'expense_target'
  | 'income_active'
  | 'income_passive';

export type Category = {
  id: number;
  user_id: number;
  name: string;
  kind: CategoryKind;
  priority: CategoryPriority;
  color: string | null;
  is_system: boolean;
  created_at: string;
  updated_at: string;
};

export type CreateCategoryPayload = {
  name: string;
  kind: CategoryKind;
  priority: CategoryPriority;
  color?: string | null;
  is_system?: boolean;
};

export type UpdateCategoryPayload = Partial<CreateCategoryPayload>;
