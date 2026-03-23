import { apiClient } from '@/lib/api/client';
import type { LoginPayload, RegisterPayload, TokenResponse, User } from '@/types/auth';

export function login(payload: LoginPayload) {
  return apiClient<TokenResponse>('/auth/login', {
    method: 'POST',
    auth: false,
    body: JSON.stringify(payload),
  });
}

export function register(payload: RegisterPayload) {
  return apiClient<User>('/auth/register', {
    method: 'POST',
    auth: false,
    body: JSON.stringify(payload),
  });
}

export function getMe() {
  return apiClient<User>('/auth/me');
}
