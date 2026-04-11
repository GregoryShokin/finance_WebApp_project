export type UserSettings = {
  user_id: number;
  large_purchase_threshold_pct: number;
  created_at: string | null;
  updated_at: string | null;
};

export type UpdateUserSettingsPayload = {
  large_purchase_threshold_pct: number;
};
