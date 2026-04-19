export type HealthCardTone = 'good' | 'warning' | 'danger';

export type SavingsRateZone = 'weak' | 'normal' | 'good';
export type DtiZone = 'normal' | 'acceptable' | 'dangerous' | 'critical';
export type LeverageZone = 'normal' | 'moderate' | 'critical';
export type DisciplineZone = 'weak' | 'medium' | 'good' | 'excellent';
export type FiZone = 'dependent' | 'partial' | 'on_way' | 'free';
export type FiScoreZone = 'start' | 'growth' | 'on_way' | 'freedom';

export type ChronicViolation = {
  category_name: string;
  months_count: number;
  overage_percent: number;
};

export type ChronicUnderperformer = {
  category_id: number;
  category_name: string;
  direction: string;
  direction_label: string;
  months_count: number;
  avg_fulfillment: number;
  trend: string;
  last_planned: number;
  last_actual: number;
};

export type UnplannedCategory = {
  category_id: number;
  category_name: string;
  direction: string;
  direction_label: string;
  avg_monthly_amount: number;
  months_with_spending: number;
};

export type DisciplineHistoryPoint = {
  month: string;
  value: number;
};

export type DirectionHeatmapRow = {
  direction: string;
  label: string;
  planned: number;
  actual: number;
  fulfillment: number;
};

export type MonthlyHealthSnapshot = {
  month: string;
  label: string;
  income: number;
  essential: number;
  secondary: number;
  planned_income: number;
  actual_income: number;
  planned_expenses: number;
  actual_expenses: number;
  savings: number;
  savings_rate: number;
  essential_rate: number;
  secondary_rate: number;
  dti: number;
  fi_score: number;
  discipline: number | null;
  direction_heatmap: DirectionHeatmapRow[];
};

export type FIScoreHistory = {
  current: number;
  previous: number;
  baseline: number;
};

// FI-score v1.4 (Phase 4, 2026-04-19): 4 components, weights 0.20+0.30+0.25+0.25
export type FIScoreComponents = {
  savings_rate: number;      // weight 0.20
  capital_trend: number;     // weight 0.30 — capital trajectory
  dti_inverse: number;       // weight 0.25
  buffer_stability: number;  // weight 0.25 — deposit months / 6 * 10
  months_calculated?: number;
  history?: FIScoreHistory;
};

export type FinancialHealth = {
  savings_rate: number;
  avg_savings_rate: number;
  savings_rate_zone: SavingsRateZone;
  monthly_avg_balance: number;
  months_calculated: number;
  daily_limit: number;
  daily_limit_with_carry: number;
  carry_over_days: number;
  dti: number;
  dti_zone: DtiZone;
  dti_total_payments: number;
  dti_income: number;
  leverage: number;
  leverage_zone: LeverageZone;
  leverage_total_debt: number;
  leverage_own_capital: number;
  real_assets_total?: number;
  discipline: number | null;
  discipline_zone: DisciplineZone | null;
  discipline_violations: ChronicViolation[];
  chronic_underperformers: ChronicUnderperformer[];
  unplanned_categories: UnplannedCategory[];
  discipline_history?: DisciplineHistoryPoint[];
  fi_percent: number;
  fi_zone: FiZone;
  fi_capital_needed: number;
  fi_passive_income: number;
  fi_monthly_gap: number;
  avg_monthly_expenses?: number;
  fi_score: number;
  fi_score_zone: FiScoreZone;
  fi_score_components: FIScoreComponents;
  monthly_history: MonthlyHealthSnapshot[];
};

export type RealAssetType = 'real_estate' | 'car' | 'other';

export type RealAsset = {
  id: number;
  asset_type: RealAssetType;
  name: string;
  estimated_value: number;
  linked_account_id: number | null;
  updated_at: string;
};

export type RealAssetPayload = {
  asset_type: RealAssetType;
  name: string;
  estimated_value: number;
  linked_account_id?: number | null;
};
