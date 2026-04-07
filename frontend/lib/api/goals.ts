import { apiClient } from '@/lib/api/client';
import type {
  CreateGoalPayload,
  Goal,
  GoalForecastResponse,
  GoalWithProgress,
  UpdateGoalPayload,
} from '@/types/goal';

export function getGoals() {
  return apiClient<GoalWithProgress[]>('/goals');
}

export function getGoal(goalId: number) {
  return apiClient<GoalWithProgress>(`/goals/${goalId}`);
}

export function createGoal(payload: CreateGoalPayload) {
  return apiClient<Goal>('/goals', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateGoal(goalId: number, payload: UpdateGoalPayload) {
  return apiClient<Goal>(`/goals/${goalId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function archiveGoal(goalId: number) {
  return apiClient<Goal>(`/goals/${goalId}/archive`, {
    method: 'POST',
  });
}

export async function getGoalForecast(params: {
  target_amount: number;
  deadline?: string | null;
  monthly_contribution?: number | null;
}): Promise<GoalForecastResponse> {
  const query = new URLSearchParams();
  query.set('target_amount', String(params.target_amount));
  if (params.deadline) query.set('deadline', params.deadline);
  if (params.monthly_contribution != null) {
    query.set('monthly_contribution', String(params.monthly_contribution));
  }
  return apiClient(`/goals/forecast?${query.toString()}`);
}
