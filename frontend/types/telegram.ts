export type TelegramStatusResponse = {
  connected: boolean;
  telegram_id: number | null;
  telegram_username: string | null;
  pending_code: string | null;
  pending_code_expires_at: string | null;
};

export type TelegramAuthPayload = {
  id: number;
  first_name?: string | null;
  last_name?: string | null;
  username?: string | null;
  photo_url?: string | null;
  auth_date: number;
  hash: string;
};

export type TelegramConnectResponse = {
  ok: boolean;
  telegram_username: string | null;
};

export type TelegramLinkCodeResponse = {
  ok: boolean;
  code: string;
  expires_at: string;
  bot_username: string;
};