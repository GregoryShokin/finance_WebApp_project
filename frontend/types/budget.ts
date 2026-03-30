export type BudgetProgress = {
  category_id: number;
  category_name: string;
  planned_amount: number;
  spent_amount: number;
  remaining: number;
  percent_used: number;
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
