import { defineConfig, devices } from '@playwright/test';
import * as dotenv from 'dotenv';
import * as path from 'path';

dotenv.config({ path: path.resolve(__dirname, '.env') });

const FRONTEND_URL = process.env.E2E_FRONTEND_URL ?? 'http://localhost:3000';

export default defineConfig({
  testDir: './specs',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // Single worker enforced project-wide. Rate-limit specs (03-rate-limit) reset
  // shared Redis buckets in beforeEach; other specs (01-auth-refresh) reset
  // the same buckets on their own beforeEach. Two workers create a race
  // where one file's reset wipes the other file's mid-test counter, causing
  // the limit-exhaustion assertion to see status 201 (under limit) instead
  // of 429. Single worker = predictable serialisation for ~30s total runtime.
  workers: 1,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'reports', open: 'never' }],
  ],
  globalSetup: require.resolve('./global-setup.ts'),
  use: {
    baseURL: FRONTEND_URL,
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
