import { apiClient } from '@/lib/api/client';
import type {
  TelegramAuthPayload,
  TelegramConnectResponse,
  TelegramLinkCodeResponse,
  TelegramStatusResponse,
} from '@/types/telegram';

export function getTelegramStatus() {
  return apiClient<TelegramStatusResponse>('/telegram/status');
}

export function connectTelegram(payload: TelegramAuthPayload) {
  return apiClient<TelegramConnectResponse>('/telegram/connect', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function createTelegramLinkCode() {
  return apiClient<TelegramLinkCodeResponse>('/telegram/link-code', {
    method: 'POST',
  });
}

export function disconnectTelegram() {
  return apiClient<{ ok: boolean }>('/telegram/disconnect', {
    method: 'DELETE',
  });
}