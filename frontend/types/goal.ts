export type GoalStatus = 'active' | 'achieved' | 'archived';
export type GoalSystemKey = 'safety_buffer';

export type Goal = {
  id: number;
  user_id: number;
  name: string;
  target_amount: number;
  deadline: string | null;
  status: GoalStatus;
  is_system: boolean;
  system_key: GoalSystemKey | null;
  created_at: string;
  updated_at: string;
};

export type GoalWithProgress = Goal & {
  saved: number;
  percent: number;
  remaining: number;
  monthly_needed: number | null;
  is_on_track: boolean | null;
  shortfall: number | null;
  estimated_date: string | null;
};

export type CreateGoalPayload = {
  name: string;
  target_amount: number;
  deadline?: string | null;
};

export type UpdateGoalPayload = {
  name?: string;
  target_amount?: number;
  deadline?: string | null;
};

export type GoalForecastResponse = {
  monthly_avg_balance: number;
  monthly_needed: number | null;
  estimated_months: number | null;
  estimated_date: string | null;
  is_achievable: boolean;
  shortfall: number | null;
  suggested_date: string | null;
  contribution_percent: number | null;
  deadline_too_close: boolean;
};
