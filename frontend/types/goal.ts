export type GoalStatus = 'active' | 'achieved' | 'archived';

export type Goal = {
  id: number;
  user_id: number;
  name: string;
  target_amount: number;
  deadline: string | null;
  status: GoalStatus;
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
};

export type UpdateGoalPayload = {
  name?: string;
  target_amount?: number;
  deadline?: string | null;
};
