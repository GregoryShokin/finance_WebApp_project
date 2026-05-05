import type { APIRequestContext } from '@playwright/test';
import { assertOk } from './api';
import type { ExtractorStatus, RateLimitScope, TestAccount, TestBank, TestUser } from './types';

interface SeedUserOpts {
  email?: string;
  password?: string;
  full_name?: string;
}

/**
 * Create or fetch a test user via `/_test/seed/user`. The endpoint is
 * idempotent on email: passing the same email twice returns the same user
 * with new tokens. Tests that need isolation must generate a unique email
 * (see `uniqueEmail()`).
 */
export async function seedUser(api: APIRequestContext, opts: SeedUserOpts = {}): Promise<TestUser> {
  const password = opts.password ?? 'Password123!';
  const email = opts.email ?? uniqueEmail();
  const full_name = opts.full_name ?? null;

  const resp = await api.post('_test/seed/user', {
    data: { email, password, full_name },
  });
  await assertOk(`seed/user(${email})`, resp);
  const body = await resp.json();
  return {
    user_id: body.user_id,
    email: body.email,
    password,
    full_name,
    access_token: body.access_token,
    refresh_token: body.refresh_token,
  };
}

export async function cleanupUser(api: APIRequestContext, email: string): Promise<void> {
  const resp = await api.post('_test/cleanup/user', { data: { email } });
  await assertOk(`cleanup/user(${email})`, resp);
}

interface SeedBankOpts {
  name: string;
  extractor_status?: ExtractorStatus;
  code?: string;
}

export async function seedBank(api: APIRequestContext, opts: SeedBankOpts): Promise<TestBank> {
  const resp = await api.post('_test/seed/bank', {
    data: { name: opts.name, extractor_status: opts.extractor_status ?? 'supported', code: opts.code },
  });
  await assertOk(`seed/bank(${opts.name})`, resp);
  return resp.json();
}

interface SeedAccountOpts {
  user_id: number;
  bank_id: number;
  name: string;
  currency?: string;
  account_type?: string;
  contract_number?: string;
}

export async function seedAccount(api: APIRequestContext, opts: SeedAccountOpts): Promise<TestAccount> {
  const resp = await api.post('_test/seed/account', { data: opts });
  await assertOk(`seed/account(${opts.name})`, resp);
  return resp.json();
}

export async function resetRateLimit(api: APIRequestContext, scope: RateLimitScope, identifier?: string): Promise<void> {
  const resp = await api.post('_test/reset/rate-limit', { data: { scope, identifier } });
  await assertOk(`reset/rate-limit(${scope})`, resp);
}

interface IssueTokensOpts {
  user_id: number;
  access_ttl_seconds?: number;
  refresh_ttl_seconds?: number;
}

export async function issueTokens(api: APIRequestContext, opts: IssueTokensOpts): Promise<{
  access_token: string;
  refresh_token: string;
}> {
  const resp = await api.post('_test/auth/issue-tokens', { data: opts });
  await assertOk(`auth/issue-tokens(user=${opts.user_id})`, resp);
  return resp.json();
}

export interface ImportSessionState {
  id: number;
  user_id: number;
  status: string;
  file_hash: string | null;
}

export async function getImportSessionState(api: APIRequestContext, sessionId: number): Promise<ImportSessionState> {
  const resp = await api.get(`_test/import-session/${sessionId}`);
  await assertOk(`import-session/${sessionId}`, resp);
  return resp.json();
}

/** Force-mark an import session as `committed`. Used by dedup test 0.5.5
 * to set up the "committed duplicate" branch without driving the full
 * upload→preview→mapping→commit UI flow.
 */
export async function markImportSessionCommitted(api: APIRequestContext, sessionId: number): Promise<ImportSessionState> {
  const resp = await api.post(`_test/import-session/${sessionId}/mark-committed`);
  await assertOk(`mark-committed(${sessionId})`, resp);
  return resp.json();
}

/**
 * Generate an email guaranteed unique for the suite run. We embed the test
 * timestamp + a small random suffix so concurrent workers (workers=2 by
 * default) don't collide.
 *
 * Domain choice: `.fake` is NOT on IANA's reserved-TLD list, while `.test`,
 * `.example`, `.invalid`, `.localhost` ARE. Pydantic's `EmailStr` (used by
 * the production auth schemas in `app/schemas/auth.py`) rejects reserved
 * TLDs, so registering/logging in with `@local.test` fails with 422 even
 * though the local DB user was seeded fine. `.fake` sidesteps that without
 * needing to weaken production validation.
 */
export function uniqueEmail(prefix = 'e2e'): string {
  const ts = Date.now();
  const rnd = Math.random().toString(36).slice(2, 8);
  return `${prefix}-${ts}-${rnd}@e2e-local.fake`;
}
