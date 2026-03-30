import { apiClient } from '@/lib/api/client';
import type { BudgetAlert, BudgetProgress } from '@/types/budget';

export function getBudgetProgress(month: string) {
  return apiClient<BudgetProgress[]>(`/budget/${month}`);
}

export function getBudgetAlerts() {
  return apiClient<BudgetAlert[]>('/budget/alerts');
}

export function markAlertRead(alertId: number) {
  return apiClient<BudgetAlert>(`/budget/alerts/${alertId}/read`, { method: 'POST' });
}

export function updateBudget(month: string, categoryId: number, plannedAmount: number) {
  return apiClient<BudgetProgress>(`/budget/${month}/${categoryId}`, {
    method: 'PUT',
    body: JSON.stringify({ planned_amount: plannedAmount }),
  });
}
