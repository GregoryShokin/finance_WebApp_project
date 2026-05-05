import { test, expect } from '@playwright/test';

const API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000/api/v1';

test.describe('00 — bootstrap smoke', () => {
  test('API /health returns {status: "ok"}', async ({ request }) => {
    const resp = await request.get(`${API_URL}/health`);
    expect(resp.ok()).toBe(true);
    const body = await resp.json();
    expect(body).toEqual({ status: 'ok' });
  });

  test('Playwright baseURL is reachable', async ({ page }) => {
    const resp = await page.goto('/');
    expect(resp?.status(), 'frontend must be running on baseURL — see e2e/README.md').toBeLessThan(500);
  });
});
