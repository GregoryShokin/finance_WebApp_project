import type { APIRequestContext, BrowserContext, Cookie, Page } from '@playwright/test';
import { SEL } from './selectors';
import type { TestUser } from './types';
import { issueTokens } from './seed';

export const ACCESS_COOKIE = 'financeapp_access_token';
export const REFRESH_COOKIE = 'financeapp_refresh_token';

/**
 * Fill the login form and submit. Asserts that the dashboard is reached.
 * For the error path (wrong password etc.) write the spec inline — don't
 * call this and expect failure.
 */
export async function loginViaUI(page: Page, user: TestUser): Promise<void> {
  await page.goto('/login');
  await page.locator(SEL.loginEmail).fill(user.email);
  await page.locator(SEL.loginPassword).fill(user.password);
  await page.locator(SEL.loginSubmit).click();
  await page.waitForURL(/\/dashboard/, { timeout: 10_000 });
}

/**
 * Fast path: skip the UI form entirely and set the auth cookies directly.
 * Use when login itself isn't under test (e.g. CC.1 happy path or any spec
 * that just needs to start authenticated).
 *
 * The frontend reads `financeapp_access_token` / `financeapp_refresh_token`
 * cookies (set client-side via `js-cookie` in `lib/auth/token.ts`). Cookies
 * are NOT HttpOnly by design — the SPA needs to read the access token to
 * attach `Authorization: Bearer …` to API calls.
 */
export async function loginViaAPI(context: BrowserContext, user: TestUser): Promise<void> {
  const frontendUrl = process.env.E2E_FRONTEND_URL ?? 'http://localhost:3000';
  const url = new URL(frontendUrl);
  await context.addCookies([
    {
      name: ACCESS_COOKIE,
      value: user.access_token,
      domain: url.hostname,
      path: '/',
      sameSite: 'Lax',
      // expires 7 days out, mirroring the production cookie options
      expires: Math.floor(Date.now() / 1000) + 7 * 24 * 60 * 60,
    },
    {
      name: REFRESH_COOKIE,
      value: user.refresh_token,
      domain: url.hostname,
      path: '/',
      sameSite: 'Strict',
      expires: Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60,
    },
  ]);
}

/**
 * Issue tokens with a custom TTL (used by 0.1.7 silent-refresh test) and
 * inject them via the same path as `loginViaAPI`.
 */
export async function loginViaAPIWithTTL(
  api: APIRequestContext,
  context: BrowserContext,
  user: TestUser,
  ttl: { access_ttl_seconds?: number; refresh_ttl_seconds?: number },
): Promise<{ access_token: string; refresh_token: string }> {
  const tokens = await issueTokens(api, {
    user_id: user.user_id,
    access_ttl_seconds: ttl.access_ttl_seconds,
    refresh_ttl_seconds: ttl.refresh_ttl_seconds,
  });
  const ephemeralUser: TestUser = { ...user, access_token: tokens.access_token, refresh_token: tokens.refresh_token };
  await loginViaAPI(context, ephemeralUser);
  return tokens;
}

/** Read access/refresh cookies from the browser context. */
export async function getAuthCookies(context: BrowserContext): Promise<{ access?: Cookie; refresh?: Cookie }> {
  const cookies = await context.cookies();
  return {
    access: cookies.find(c => c.name === ACCESS_COOKIE),
    refresh: cookies.find(c => c.name === REFRESH_COOKIE),
  };
}

/** Delete one or both auth cookies in the current context. */
export async function deleteAuthCookie(context: BrowserContext, which: 'access' | 'refresh' | 'both'): Promise<void> {
  const all = await context.cookies();
  const target = (name: string) =>
    (which === 'both' || (which === 'access' && name === ACCESS_COOKIE) || (which === 'refresh' && name === REFRESH_COOKIE));
  const toKeep = all.filter(c => !target(c.name));
  await context.clearCookies();
  if (toKeep.length > 0) {
    await context.addCookies(toKeep);
  }
}
