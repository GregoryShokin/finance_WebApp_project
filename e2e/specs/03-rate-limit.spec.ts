/**
 * Stage 0.3 — Rate limits.
 *
 * Backend caps (from app/core/config.py + .env):
 *   /auth/login      — 5 / 15 minutes per IP
 *   /auth/register   — 3 / hour per IP
 *   /imports/upload  — 30 / hour per user-or-ip
 *
 * 429 contract (app/core/rate_limit.py:rate_limit_exceeded_handler):
 *   status: 429
 *   header: Retry-After: <seconds>
 *   body: { detail, code: "rate_limit_exceeded", endpoint, retry_after_seconds }
 *
 * Serial mode: rate buckets are global per IP; running these tests in
 * parallel with the rest of the suite would burn quotas mid-run. We force
 * `serial` here AND blanket-reset every scope in beforeEach so consecutive
 * `npm run test:smoke` calls don't see each other's residue.
 */
import { test, expect, type APIRequestContext } from '@playwright/test';
import { newApi, apiBaseUrl } from '../helpers/api';
import { cleanupUser, resetRateLimit, seedUser, uniqueEmail } from '../helpers/seed';
import { uploadFile } from '../helpers/upload';
import { getAdversarialPath } from '../helpers/files';

test.describe.configure({ mode: 'serial' });

let api: APIRequestContext;

test.beforeAll(async () => {
  api = await newApi();
});

test.afterAll(async () => {
  await api.dispose();
});

test.beforeEach(async () => {
  // Every rate-limit test must start with a clean slate. We blanket-reset
  // all four buckets the suite touches so a previous failed run doesn't
  // leak counters into the next one.
  await resetRateLimit(api, 'login');
  await resetRateLimit(api, 'register');
  await resetRateLimit(api, 'refresh');
  await resetRateLimit(api, 'upload');
});

// ---------------------------------------------------------------------------
// 0.3.1 — login: 5/15min per IP. 5 attempts succeed-or-fail; 6th → 429.
//
// We use bad-password attempts (each returns 401) so the counter increments
// without creating side effects. The decorator runs inside the dependency
// cycle, so the limiter fires regardless of the route's own status code.
// ---------------------------------------------------------------------------

test('0.3.1 login: после 5 попыток за окно 6-я → 429 + Retry-After', async () => {
  const user = await seedUser(api);

  // Burn the bucket: 5 wrong-password attempts. Each returns 401 (or 429 if
  // the bucket is somehow already partially full from a stray test —
  // beforeEach should have cleared, but tolerate the boundary just in case).
  for (let i = 1; i <= 5; i++) {
    const r = await api.post('auth/login', {
      data: { email: user.email, password: 'wrong-password-x' },
    });
    expect([401, 429]).toContain(r.status());
  }

  // 6th attempt — must be 429.
  const sixth = await api.post('auth/login', {
    data: { email: user.email, password: user.password },
  });
  expect(sixth.status(), 'login bucket exhausted, expected 429').toBe(429);
  const body = await sixth.json();
  expect(body.code).toBe('rate_limit_exceeded');
  expect(body.retry_after_seconds).toBeGreaterThan(0);
  expect(sixth.headers()['retry-after']).toBeTruthy();

  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.3.2 — register: 3/hour per IP. 3 attempts (any outcome) consume the
// bucket; 4th → 429. We use unique emails so the registration itself
// succeeds (201); the limiter still increments either way.
// ---------------------------------------------------------------------------

test('0.3.2 register: после 3 регистраций 4-я → 429', async () => {
  const emails: string[] = [];
  for (let i = 1; i <= 3; i++) {
    const email = uniqueEmail('rl-reg');
    emails.push(email);
    const r = await api.post('auth/register', {
      data: { email, password: 'Password123!', full_name: `RL Reg ${i}` },
    });
    expect([201, 409, 429]).toContain(r.status());
  }

  // 4th attempt — must be 429 even with a fresh email.
  const fourthEmail = uniqueEmail('rl-reg');
  emails.push(fourthEmail);
  const fourth = await api.post('auth/register', {
    data: { email: fourthEmail, password: 'Password123!', full_name: 'RL Reg 4' },
  });
  expect(fourth.status(), 'register bucket exhausted').toBe(429);
  const body = await fourth.json();
  expect(body.code).toBe('rate_limit_exceeded');
  expect(body.retry_after_seconds).toBeGreaterThan(0);

  // Cleanup any users that were actually created (status 201).
  for (const email of emails) {
    await cleanupUser(api, email);
  }
});

// ---------------------------------------------------------------------------
// 0.3.3 — upload: 30/hour per user-or-ip. Burn 30 fast-rejected uploads
// (empty.csv → 415 from validator), then 31st → 429.
//
// Why empty.csv: it goes straight through the @limiter.limit decorator
// (which increments the counter) and then trips the validator's empty_file
// branch — no recognition, no DB writes, fast.
// ---------------------------------------------------------------------------

test('0.3.3 upload: после 30 загрузок 31-я → 429', async () => {
  const user = await seedUser(api);
  const fixture = getAdversarialPath('empty.csv');

  // 30 burning shots — each returns 415 (validator) but increments the
  // limiter counter regardless.
  for (let i = 1; i <= 30; i++) {
    const r = await uploadFile(api, user.access_token, fixture);
    expect([415, 429]).toContain(r.status());
  }

  // 31st — must be 429.
  const limited = await uploadFile(api, user.access_token, fixture);
  expect(limited.status(), 'upload bucket exhausted').toBe(429);
  const body = await limited.json();
  expect(body.code).toBe('rate_limit_exceeded');
  expect(body.retry_after_seconds).toBeGreaterThan(0);

  await cleanupUser(api, user.email);
});

// Silence unused-import lint when this constant ends up as a leftover after
// future edits — apiBaseUrl() is exported from helpers/api but not needed
// in this spec because all helpers go through `api`.
void apiBaseUrl;
