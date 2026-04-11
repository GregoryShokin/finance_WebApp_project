import { apiClient } from '@/lib/api/client';
import type { UpdateUserSettingsPayload, UserSettings } from '@/types/user-settings';

export function getUserSettings() {
  return apiClient<UserSettings>('/users/settings');
}

export function updateUserSettings(payload: UpdateUserSettingsPayload) {
  return apiClient<UserSettings>('/users/settings', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}
