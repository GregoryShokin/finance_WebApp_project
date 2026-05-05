import { request, type APIRequestContext } from '@playwright/test';

const RAW = process.env.E2E_API_URL ?? 'http://localhost:8000/api/v1';
// Trailing slash is mandatory: `new URL('seed/user', 'http://x/api/v1')`
// drops `/api/v1`, while `new URL('seed/user', 'http://x/api/v1/')` keeps
// it. Helpers below pass paths without a leading slash on purpose.
const API_URL = RAW.endsWith('/') ? RAW : `${RAW}/`;

export function apiBaseUrl(): string {
  return API_URL;
}

/**
 * Returns a fresh Playwright APIRequestContext targeted at the backend.
 * Each test creates its own — they are cheap and ensure no cookie / header
 * pollution across tests. Caller must `dispose()` it.
 *
 * IMPORTANT: pass paths WITHOUT a leading slash (e.g. `_test/seed/user`),
 * otherwise the `/api/v1` portion of the baseURL gets stripped by URL
 * resolution rules.
 */
export async function newApi(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: API_URL });
}

/** Throws with a useful message if the response isn't OK. */
export async function assertOk(label: string, resp: import('@playwright/test').APIResponse): Promise<void> {
  if (!resp.ok()) {
    let body: string;
    try {
      body = await resp.text();
    } catch {
      body = '<no body>';
    }
    throw new Error(`${label} failed: ${resp.status()} ${resp.statusText()}\n${body.slice(0, 500)}`);
  }
}
