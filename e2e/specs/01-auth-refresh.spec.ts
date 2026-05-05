/**
 * Stage 0.1 — Auth + refresh-token flow. 12 scenarios, all in this file.
 *
 * Cookie note: the frontend stores tokens in JS-readable cookies
 * (`financeapp_access_token`, `financeapp_refresh_token`) — NOT HttpOnly.
 * This is intentional: the SPA needs to read the access token to attach
 * `Authorization: Bearer …` to API calls. Tests assert presence + sameSite
 * + expiry but don't assert `httpOnly` because it would always fail.
 *
 * Architecture nuance for 0.1.4 / 0.1.6: route protection is double-gated.
 * Next.js middleware (frontend/middleware.ts) checks for the access cookie's
 * PRESENCE (not validity) on every request and 302s to /login when missing.
 * Then, once the SPA mounts and fires API calls, the apiClient
 * (frontend/lib/api/client.ts) handles 401 responses by silent-refresh.
 * That means "delete access cookie" tests cannot exercise silent refresh —
 * middleware redirects before the SPA loads. To test silent refresh under
 * cookie auth, the access cookie must be PRESENT but INVALID (corrupted
 * value) so middleware passes and the backend returns 401 — see 0.1.4.
 */
import { test, expect, type APIRequestContext } from '@playwright/test';
import { SEL } from '../helpers/selectors';
import { ACCESS_COOKIE, REFRESH_COOKIE, getAuthCookies, loginViaAPI, loginViaAPIWithTTL } from '../helpers/auth';
import { newApi, apiBaseUrl } from '../helpers/api';
import { cleanupUser, issueTokens, resetRateLimit, seedUser, uniqueEmail } from '../helpers/seed';
import { startNetworkLog } from '../helpers/network';

let api: APIRequestContext;

test.beforeAll(async () => {
  api = await newApi();
});

test.afterAll(async () => {
  await api.dispose();
});

test.beforeEach(async () => {
  // Auth specs share a single rate-limit bucket per IP. Without this, running
  // the suite locally a second time inside 15 minutes would burn quotas and
  // start seeing 429s instead of the expected statuses. Reset all three
  // /auth/* buckets — refresh in particular is exercised by 0.1.4/7/8/10/12
  // and the 30/5min cap fills in two consecutive runs.
  await resetRateLimit(api, 'login');
  await resetRateLimit(api, 'register');
  await resetRateLimit(api, 'refresh');
});

test('0.1.1 регистрация: после submit оказываемся на /dashboard и видим обе auth-cookie', async ({ page, context }) => {
  const email = uniqueEmail('reg');
  const password = 'Password123!';

  await page.goto('/register');
  await page.locator(SEL.registerFullName).fill('E2E User');
  await page.locator(SEL.registerEmail).fill(email);
  await page.locator(SEL.registerPassword).fill(password);
  await page.locator(SEL.registerConfirmPassword).fill(password);
  await page.locator(SEL.registerSubmit).click();

  await page.waitForURL(/\/dashboard/, { timeout: 10_000 });

  const { access, refresh } = await getAuthCookies(context);
  expect(access, 'access cookie must be set after register+login').toBeDefined();
  expect(refresh, 'refresh cookie must be set after register+login').toBeDefined();
  expect(access!.value.length, 'access cookie value must be a non-empty JWT').toBeGreaterThan(20);
  expect(refresh!.value.length).toBeGreaterThan(20);
  expect(access!.sameSite).toBe('Lax');
  expect(refresh!.sameSite).toBe('Strict');
  // expires is a unix timestamp — must be in the future
  expect(access!.expires).toBeGreaterThan(Date.now() / 1000);
  expect(refresh!.expires).toBeGreaterThan(Date.now() / 1000);

  await cleanupUser(api, email);
});

test('0.1.2 login существующего юзера: cookies проставляются, /dashboard достижим', async ({ page, context }) => {
  const user = await seedUser(api);
  // Clear cookies first — seedUser inside the API context doesn't pollute the
  // browser context, but be defensive in case a previous test leaked.
  await context.clearCookies();

  await page.goto('/login');
  await page.locator(SEL.loginEmail).fill(user.email);
  await page.locator(SEL.loginPassword).fill(user.password);
  await page.locator(SEL.loginSubmit).click();

  await page.waitForURL(/\/dashboard/, { timeout: 10_000 });

  const cookies = await context.cookies();
  expect(cookies.find(c => c.name === ACCESS_COOKIE), 'access cookie present').toBeDefined();
  expect(cookies.find(c => c.name === REFRESH_COOKIE), 'refresh cookie present').toBeDefined();

  await cleanupUser(api, user.email);
});

test('0.1.3 login wrong password: 401, error toast виден, cookies не появляются', async ({ page, context }) => {
  const user = await seedUser(api);
  await context.clearCookies();

  await page.goto('/login');
  await page.locator(SEL.loginEmail).fill(user.email);
  await page.locator(SEL.loginPassword).fill('wrong-password-' + Date.now());

  // Capture the /auth/login response
  const loginRespPromise = page.waitForResponse(
    r => r.url().includes('/auth/login') && r.request().method() === 'POST',
    { timeout: 10_000 },
  );
  await page.locator(SEL.loginSubmit).click();
  const loginResp = await loginRespPromise;
  expect(loginResp.status(), 'wrong password must produce 401').toBe(401);

  // Error toast (sonner) appears
  await expect(page.locator(SEL.toastError)).toBeVisible({ timeout: 5_000 });

  // No tokens were set
  const cookies = await context.cookies();
  expect(cookies.find(c => c.name === ACCESS_COOKIE), 'access cookie must NOT appear on bad login').toBeUndefined();
  expect(cookies.find(c => c.name === REFRESH_COOKIE), 'refresh cookie must NOT appear on bad login').toBeUndefined();

  // Still on /login
  expect(page.url()).toContain('/login');

  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.1.4 — Silent refresh on invalid access token.
//
// ТЗ pseudocode: «удалить access cookie → goto /transactions → ждать /auth/refresh».
// Reality: deleting the access cookie hits the middleware redirect FIRST —
// the SPA never loads, no silent-refresh path. To exercise the actual
// apiClient.ensureRefresh() flow we corrupt the cookie value while keeping
// it present, so middleware lets the request through, the SPA mounts, fires
// API calls → backend rejects (bad signature) → silent refresh fires.
// ---------------------------------------------------------------------------

test('0.1.4 silent refresh при битом access cookie: SPA вызывает /auth/refresh и продолжает работать', async ({ page, context }) => {
  const user = await seedUser(api);
  await context.clearCookies();
  await loginViaAPI(context, user);

  // Replace access cookie with garbage. Middleware checks presence only,
  // backend will return 401 on the first protected API call.
  const cookies = await context.cookies();
  const access = cookies.find(c => c.name === ACCESS_COOKIE);
  expect(access, 'precondition: loginViaAPI set access cookie').toBeDefined();
  await context.clearCookies({ name: ACCESS_COOKIE });
  await context.addCookies([{
    ...access!,
    value: 'corrupted.invalid.token',
  }]);

  const log = startNetworkLog(page);
  // Wait for /auth/me explicitly (see 0.1.7 for race details).
  const meResponsePromise = page.waitForResponse(
    r => r.url().endsWith('/auth/me') && r.request().method() === 'GET',
    { timeout: 15_000 },
  );
  await page.goto('/dashboard');
  await meResponsePromise;
  await page.waitForLoadState('networkidle', { timeout: 5_000 });

  // Exactly one /auth/refresh fired and succeeded.
  const refreshCalls = log.calls('POST', '/auth/refresh');
  expect(refreshCalls.length, 'silent refresh must fire on 401').toBeGreaterThanOrEqual(1);
  expect(refreshCalls[0].response?.status(), '/auth/refresh must succeed').toBe(200);

  // No redirect to /login (silent refresh recovered the session).
  expect(page.url(), 'session recovered, no /login redirect').toContain('/dashboard');

  // New access cookie was written.
  const after = await getAuthCookies(context);
  expect(after.access?.value).not.toBe('corrupted.invalid.token');
  expect(after.access?.value.length).toBeGreaterThan(20);

  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.1.5 — Logout via UI clears cookies AND revokes refresh server-side.
//
// Server-side revocation matters: a client that hangs onto the old refresh
// token (e.g. saved in another tab) must NOT be able to mint new access
// tokens. Test asserts both UI state and backend rejection.
// ---------------------------------------------------------------------------

test('0.1.5 logout: cookies очищены, старый refresh не работает', async ({ page, context }) => {
  const user = await seedUser(api);
  await context.clearCookies();
  await loginViaAPI(context, user);

  // Capture the refresh token before logout for the post-revoke check.
  const before = await getAuthCookies(context);
  const oldRefresh = before.refresh!.value;

  // Logout via the same path the UI uses — POST /auth/logout with refresh body.
  const logoutResp = await page.request.post(`${apiBaseUrl()}auth/logout`, {
    data: { refresh_token: oldRefresh },
  });
  expect(logoutResp.status(), 'logout returns 204').toBe(204);

  // Mirror the frontend's clearTokens() — sidebar logout button does this client-side.
  await context.clearCookies({ name: ACCESS_COOKIE });
  await context.clearCookies({ name: REFRESH_COOKIE });
  const after = await getAuthCookies(context);
  expect(after.access).toBeUndefined();
  expect(after.refresh).toBeUndefined();

  // The old refresh token is now revoked — attempting to use it must fail.
  const refreshResp = await page.request.post(`${apiBaseUrl()}auth/refresh`, {
    data: { refresh_token: oldRefresh },
  });
  expect(refreshResp.status(), 'revoked refresh token must return 401').toBe(401);

  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.1.6 — Protected route after logout redirects to /login.
//
// This is the middleware contract — without an access cookie, /dashboard
// (and every other appRoute in middleware.ts) issues a 302 to /login.
// ---------------------------------------------------------------------------

test('0.1.6 после logout protected route редиректит на /login', async ({ page, context }) => {
  const user = await seedUser(api);
  await context.clearCookies();
  await loginViaAPI(context, user);

  // Logout (ignore the actual call — we're testing client-side state only).
  await context.clearCookies();

  await page.goto('/dashboard');
  await page.waitForURL(/\/login/, { timeout: 10_000 });
  expect(page.url(), 'middleware redirect to /login').toContain('/login');

  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.1.7 — Long session: expired access token triggers silent refresh.
//
// Real ACCESS_TOKEN_EXPIRE_MINUTES is 2880 (2 days). To exercise the silent
// refresh flow without sleeping for 2 days, /_test/auth/issue-tokens accepts
// a custom TTL. Token expires in 1 second; we sleep 2s; navigate; backend
// returns 401 on the first protected call → SPA refreshes silently.
// ---------------------------------------------------------------------------

test('0.1.7 истёкший access (TTL=1s) → silent refresh без редиректа', async ({ page, context }) => {
  const user = await seedUser(api);
  await context.clearCookies();
  await loginViaAPIWithTTL(api, context, user, { access_ttl_seconds: 1 });

  // Wait past the TTL. waitForTimeout justified per ТЗ §6.5: JWT exp is a
  // wall-clock claim with no observable signal. 2.5s margin on a 1s TTL
  // covers Docker↔host clock drift; tighter sleeps flake.
  await page.waitForTimeout(2_500);

  const log = startNetworkLog(page);
  // Wait for the actual /auth/me roundtrip rather than networkidle — useAuth
  // gates the query on a useEffect setMounted(true) which can fire AFTER
  // initial networkidle settles, leaving the assertion racing the SPA.
  const meResponsePromise = page.waitForResponse(
    r => r.url().endsWith('/auth/me') && r.request().method() === 'GET',
    { timeout: 15_000 },
  );
  await page.goto('/dashboard');
  await meResponsePromise;
  // Brief grace for the silent-refresh response to be recorded by the log.
  await page.waitForLoadState('networkidle', { timeout: 5_000 });

  const refreshCalls = log.calls('POST', '/auth/refresh');
  expect(refreshCalls.length, 'expired access must trigger silent refresh').toBeGreaterThanOrEqual(1);
  expect(refreshCalls[0].response?.status()).toBe(200);
  expect(page.url(), 'no /login redirect after silent refresh').toContain('/dashboard');

  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.1.8 — Singleton refresh under concurrent 401s.
//
// /dashboard fires several React Query queries in parallel (metrics,
// accounts, transactions...). With expired access, all of them get 401
// near-simultaneously. apiClient.ensureRefresh() collapses concurrent
// refreshes onto a single in-flight promise (see refreshPromise singleton
// in lib/api/client.ts). Result: exactly one POST /auth/refresh.
// ---------------------------------------------------------------------------

test('0.1.8 параллельные 401 → ровно один /auth/refresh (singleton)', async ({ page, context }) => {
  const user = await seedUser(api);
  await context.clearCookies();
  await loginViaAPIWithTTL(api, context, user, { access_ttl_seconds: 1 });
  await page.waitForTimeout(2_500); // see 0.1.7 for justification

  const log = startNetworkLog(page);
  // Same race as 0.1.7 — wait for /auth/me explicitly instead of networkidle,
  // because useAuth's mounted-flag race can resolve networkidle before any
  // protected API call has fired.
  const meResponsePromise = page.waitForResponse(
    r => r.url().endsWith('/auth/me') && r.request().method() === 'GET',
    { timeout: 15_000 },
  );
  await page.goto('/dashboard');
  await meResponsePromise;
  await page.waitForLoadState('networkidle', { timeout: 5_000 });

  const refreshCalls = log.calls('POST', '/auth/refresh');
  expect(
    refreshCalls.length,
    `singleton must collapse concurrent refreshes to one — got ${refreshCalls.length}`,
  ).toBe(1);

  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.1.9 — Multi-device: two contexts with independent sessions.
//
// Login is multi-device by design (auth_service.py: no revocation of other
// sessions on new login). Two separate browser contexts logging in for the
// same user must both work concurrently — no session steals the other.
// Mirrors the existing pytest test_login_does_not_revoke_existing_sessions.
// ---------------------------------------------------------------------------

test('0.1.9 multi-device: два контекста, оба авторизованы независимо', async ({ browser }) => {
  const user = await seedUser(api);

  const ctxDesktop = await browser.newContext();
  const ctxMobile = await browser.newContext();

  // Issue separate token pairs — simulates two real logins on different
  // devices. Each pair gets its own DB record.
  const desktopTokens = await issueTokens(api, { user_id: user.user_id });
  const mobileTokens = await issueTokens(api, { user_id: user.user_id });

  await loginViaAPI(ctxDesktop, { ...user, access_token: desktopTokens.access_token, refresh_token: desktopTokens.refresh_token });
  await loginViaAPI(ctxMobile, { ...user, access_token: mobileTokens.access_token, refresh_token: mobileTokens.refresh_token });

  const desktopPage = await ctxDesktop.newPage();
  const mobilePage = await ctxMobile.newPage();

  await desktopPage.goto('/dashboard');
  await mobilePage.goto('/dashboard');

  await expect(desktopPage).toHaveURL(/\/dashboard/, { timeout: 10_000 });
  await expect(mobilePage).toHaveURL(/\/dashboard/, { timeout: 10_000 });

  // Both contexts can still hit a protected endpoint.
  const desktopMe = await ctxDesktop.request.get(`${apiBaseUrl()}auth/me`, {
    headers: { Authorization: `Bearer ${desktopTokens.access_token}` },
  });
  const mobileMe = await ctxMobile.request.get(`${apiBaseUrl()}auth/me`, {
    headers: { Authorization: `Bearer ${mobileTokens.access_token}` },
  });
  expect(desktopMe.status()).toBe(200);
  expect(mobileMe.status()).toBe(200);

  await ctxDesktop.close();
  await ctxMobile.close();
  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.1.10 — Refresh-token reuse triggers revoke_all_for_user.
//
// Production guarantee: if the SAME refresh token is presented twice (the
// second time after rotation has happened), every active refresh for that
// user is revoked. Mirrors pytest test_revoked_refresh_triggers_reuse_detection_revokes_all.
//
// Setup: login produces refresh R1. Use R1 to refresh → success, returns R2
// and revokes R1. Now use R1 AGAIN — backend detects reuse and revokes both
// R1 and R2. The second user (or device) holding any token can no longer
// refresh.
// ---------------------------------------------------------------------------

test('0.1.10 reuse-detection: повторное использование refresh → revoke_all', async () => {
  const user = await seedUser(api);

  // First refresh — rotates R1 into R2. Use raw API context, not the SPA,
  // so we can observe the failure directly without UI noise.
  const r1 = user.refresh_token;
  const firstRotation = await api.post('auth/refresh', { data: { refresh_token: r1 } });
  expect(firstRotation.status(), 'first rotation succeeds').toBe(200);
  const { refresh_token: r2 } = await firstRotation.json();
  expect(r2).not.toBe(r1);

  // Replay R1 — this is the reuse signal. Backend revokes EVERY active token.
  const replay = await api.post('auth/refresh', { data: { refresh_token: r1 } });
  expect(replay.status(), 'replayed refresh must be rejected').toBe(401);

  // R2 is now also revoked, even though it was never replayed itself.
  const r2Attempt = await api.post('auth/refresh', { data: { refresh_token: r2 } });
  expect(r2Attempt.status(), 'R2 revoked as collateral of R1 reuse').toBe(401);

  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.1.11 — Garbage refresh token → 401 (no crash, no leak).
// Mirrors pytest test_garbage_token_rejected_on_refresh.
// ---------------------------------------------------------------------------

test('0.1.11 garbage refresh token → 401', async () => {
  const resp = await api.post('auth/refresh', {
    data: { refresh_token: 'this-is-not-a-jwt' },
  });
  expect(resp.status()).toBe(401);
});

// ---------------------------------------------------------------------------
// 0.1.12 — Expired refresh token → 401 (no revoke_all).
//
// The expiry-vs-reuse distinction matters: expiry is a benign timeout, reuse
// is hostile. Backend only triggers revoke_all on reuse. We verify expiry
// returns 401 cleanly. Issue a 2-second-TTL refresh, sleep 3s, attempt.
// ---------------------------------------------------------------------------

test('0.1.12 expired refresh token → 401', async () => {
  const user = await seedUser(api);
  const tokens = await issueTokens(api, {
    user_id: user.user_id,
    refresh_ttl_seconds: 2,
  });

  // Wait past TTL. waitForTimeout justified: JWT exp is wall-clock only.
  await new Promise(resolve => setTimeout(resolve, 2_500));

  const resp = await api.post('auth/refresh', { data: { refresh_token: tokens.refresh_token } });
  expect(resp.status(), 'expired refresh must return 401').toBe(401);

  await cleanupUser(api, user.email);
});
