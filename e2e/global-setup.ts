import { request, type FullConfig } from '@playwright/test';
import * as dotenv from 'dotenv';
import * as path from 'path';

dotenv.config({ path: path.resolve(__dirname, '.env') });

const API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000/api/v1';
const FRONTEND_URL = process.env.E2E_FRONTEND_URL ?? 'http://localhost:3000';
const SKIP_FRONTEND = process.env.E2E_SKIP_FRONTEND_CHECK === '1';

async function checkUrl(label: string, url: string, expectedShape?: (body: string) => boolean): Promise<void> {
  const ctx = await request.newContext();
  try {
    const resp = await ctx.get(url, { timeout: 5_000 });
    if (!resp.ok()) {
      throw new Error(`${label}: ${url} returned ${resp.status()}`);
    }
    if (expectedShape) {
      const body = await resp.text();
      if (!expectedShape(body)) {
        throw new Error(`${label}: ${url} returned unexpected body: ${body.slice(0, 200)}`);
      }
    }
  } catch (err) {
    const hint = label === 'API'
      ? '  → did you run `docker compose up --build` in the repo root?'
      : '  → did you run `cd frontend && npm run dev`?';
    throw new Error(`E2E pre-flight failed.\n${(err as Error).message}\n${hint}`);
  } finally {
    await ctx.dispose();
  }
}

export default async function globalSetup(_config: FullConfig): Promise<void> {
  await checkUrl('API', `${API_URL}/health`, body => body.includes('"status"') && body.includes('"ok"'));
  if (!SKIP_FRONTEND) {
    await checkUrl('Frontend', FRONTEND_URL);
  }
  // Phase 1+ will add: ensure ENABLE_TEST_ENDPOINTS=true on backend by hitting
  // /_test/seed/user with a probe and asserting it doesn't 404.
}
