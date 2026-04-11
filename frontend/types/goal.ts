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
  category_id: number | null;
  created_at: string;
  updated_at: string;
};

export type GoalWithProgress = Goal & {
  saved: number;
  percent: number;
  remaining: number;
  monthly_needed: number | null;
};

export type CreateGoalPayload = {
  name: string;
  target_amount: number;
  deadline?: string | null;
  category_id?: number | null;
};

export type UpdateGoalPayload = {
  name?: string;
  target_amount?: number;
  deadline?: string | null;
  category_id?: number | null;
};
