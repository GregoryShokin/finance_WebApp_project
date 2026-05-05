export interface TestUser {
  user_id: number;
  email: string;
  password: string;
  full_name: string | null;
  access_token: string;
  refresh_token: string;
}

export interface TestBank {
  bank_id: number;
  name: string;
  extractor_status: ExtractorStatus;
  created: boolean;
  previous_extractor_status: ExtractorStatus | null;
}

export interface TestAccount {
  account_id: number;
}

export type ExtractorStatus = 'supported' | 'in_review' | 'pending' | 'broken';
export type RateLimitScope = 'login' | 'register' | 'refresh' | 'upload' | 'bot_upload';
