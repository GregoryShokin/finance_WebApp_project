export type BudgetProgress = {
  category_id: number;
  category_name: string;
  category_kind: 'income' | 'expense';
  category_priority: string;
  income_type: 'active' | 'passive' | null;
  exclude_from_planning: boolean;
  planned_amount: number;
  suggested_amount: number;
  spent_amount: number;
  remaining: number;
  percent_used: number;
};

export type FinancialIndependenceStatus = 'starting' | 'growing' | 'independent';

export type FinancialIndependence = {
  passive_income: number;
  active_income: number;
  total_expenses: number;
  percent: number;
  status: FinancialIndependenceStatus;
};

export type BudgetAlertType = 'budget_80_percent' | 'anomaly' | 'month_end_forecast';

export type BudgetAlert = {
  id: number;
  alert_type: BudgetAlertType;
  category_id: number | null;
  message: string;
  triggered_at: string;
  is_read: boolean;
};
