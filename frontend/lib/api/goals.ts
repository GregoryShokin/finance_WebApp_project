import { apiClient } from '@/lib/api/client';
import type { CreateGoalPayload, Goal, GoalWithProgress, UpdateGoalPayload } from '@/types/goal';

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
