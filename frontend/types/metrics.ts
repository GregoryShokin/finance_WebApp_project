export type FinancialIndependenceMetric = {
  percent: number;
  passive_income: number;
  avg_expenses: number;
  gap: number;
  months_of_data: number;
};

export type SavingsRateMetric = {
  percent: number;
  invested: number;
  total_income: number;
};

export type Metrics = {
  financial_independence: FinancialIndependenceMetric | null;
  savings_rate: SavingsRateMetric;
};
