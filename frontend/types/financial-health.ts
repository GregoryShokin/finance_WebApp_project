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

export type DisciplineHistoryPoint = {
  month: string;
  value: number;
};

export type FIScoreHistory = {
  current: number;
  previous: number;
  baseline: number;
};

export type FIScoreComponents = {
  savings_rate: number;
  discipline: number;
  financial_independence: number;
  capital_growth: number;
  dti_inverse: number;
  months_calculated?: number;
  history?: FIScoreHistory;
};

export type FinancialHealth = {
  savings_rate: number;
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
  discipline_history?: DisciplineHistoryPoint[];
  fi_percent: number;
  fi_zone: FiZone;
  fi_capital_needed: number;
  fi_passive_income: number;
  avg_monthly_expenses?: number;
  fi_score: number;
  fi_score_zone: FiScoreZone;
  fi_score_components: FIScoreComponents;
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
