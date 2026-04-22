export type RuleScope = 'exact' | 'bank' | 'global' | 'legacy_pattern';

export type CategoryRule = {
  id: number;
  normalized_description: string;
  original_description: string | null;
  user_label: string | null;
  category_id: number;
  confirms: number;
  rejections: number;
  scope: RuleScope;
  is_active: boolean;
  bank_code: string | null;
  account_id_scope: number | null;
  identifier_key: string | null;
  identifier_value: string | null;
  created_at: string;
  updated_at: string;
};

export type CategoryRuleFilters = {
  scope?: RuleScope;
  is_active?: boolean;
};
