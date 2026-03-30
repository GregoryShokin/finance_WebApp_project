export type HealthStatus = 'normal' | 'warning' | 'danger';

export type DebtRatioInfo = {
  value: number;
  status: HealthStatus;
  total_debt: number;
  total_assets: number;
};

export type FinancialHealth = {
  dti_value: number;
  dti_status: HealthStatus;
  debt_ratio_basic: DebtRatioInfo;
  debt_ratio_extended: DebtRatioInfo | null;
};

export type RealAssetType = 'real_estate' | 'car' | 'other';

export type RealAsset = {
  id: number;
  asset_type: RealAssetType;
  name: string;
  estimated_value: number;
  updated_at: string;
};

export type RealAssetPayload = {
  asset_type: RealAssetType;
  name: string;
  estimated_value: number;
};
