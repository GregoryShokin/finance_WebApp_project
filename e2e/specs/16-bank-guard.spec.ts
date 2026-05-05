/**
 * Stage 1.6 — Bank-supported guard.
 *
 * Production guarantee (app/services/import_service.py:upload_source):
 *   - The guard fires when an upload AUTO-MATCHES an account (via
 *     contract_number / statement_account_number on the user's accounts)
 *     AND that account's bank has `extractor_status != 'supported'`.
 *   - Three rejection statuses behave identically: `pending`, `in_review`,
 *     `broken`. Frontend tone differs per status; backend gate is binary.
 *   - No auto-match → guard never fires; user assigns an account manually
 *     in the queue (frontend disclaimer is the proactive line of defence).
 *
 * Test setup uses the UPSERT semantics of `_test/seed/bank` to flip Т-Банк's
 * status into pending/in_review/broken on the fly, then restores `supported`
 * in afterAll. ТЗ §6 chose this over needing an unsupported-bank fixture.
 *
 * Real anonymized fixture: `Т банк дебет.pdf` from Bank-extracts/.
 * The extractor surfaces `contract_number='5452737298'` for that PDF.
 * Tests seed an account with that contract under bank_id=Т-Банк so the
 * recognition layer auto-matches → guard becomes reachable.
 *
 * SERIAL describe-block: this spec mutates the global Т-Банк row. Running
 * its tests in parallel with anything else that imports a Т-Банк statement
 * would cause cross-test interference. The suite-wide workers=1 already
 * enforces serial execution; the explicit `mode: 'serial'` is kept here
 * as an in-file safeguard for any future reconfiguration.
 */
import { test, expect, type APIRequestContext } from '@playwright/test';
import { newApi } from '../helpers/api';
import {
  cleanupUser,
  resetRateLimit,
  seedAccount,
  seedBank,
  seedUser,
} from '../helpers/seed';
import { uploadFile } from '../helpers/upload';
import { getStatementPath } from '../helpers/files';
import type { ExtractorStatus, TestUser } from '../helpers/types';

test.describe.configure({ mode: 'serial' });

const BANK_NAME = 'Т-Банк';
const TBANK_CONTRACT = '5452737298';
const FIXTURE = (): string => getStatementPath('Т банк дебет.pdf');

let api: APIRequestContext;
let bankId: number;
let originalStatus: ExtractorStatus;

test.beforeAll(async () => {
  api = await newApi();
  // Capture the live status. UPSERT with `supported` returns
  // previous_extractor_status — that's what we restore in afterAll.
  const probe = await seedBank(api, { name: BANK_NAME, extractor_status: 'supported' });
  bankId = probe.bank_id;
  // If the bank was already `supported`, previous_extractor_status is null
  // (UPSERT returns null when no real change happened). Either way, the
  // safe restoration target is `supported` per the migration baseline.
  originalStatus = (probe.previous_extractor_status ?? 'supported') as ExtractorStatus;
});

test.afterAll(async () => {
  // Restore even if a test threw. Without this, Т-Банк would stay flipped
  // for the next test run and 1.6.1 would start failing in a hard-to-debug
  // way (a pristine new run would suddenly see 415).
  await seedBank(api, { name: BANK_NAME, extractor_status: originalStatus });
  await api.dispose();
});

test.beforeEach(async () => {
  await resetRateLimit(api, 'upload');
});

async function setupUserWithMatchingAccount(): Promise<TestUser> {
  const user = await seedUser(api);
  await seedAccount(api, {
    user_id: user.user_id,
    bank_id: bankId,
    name: 'T-Bank Debit (e2e)',
    contract_number: TBANK_CONTRACT,
  });
  return user;
}

// ---------------------------------------------------------------------------
// 1.6.1 — Happy path: Т-Банк supported + matching account → 201, suggested.
// ---------------------------------------------------------------------------

test('1.6.1 supported bank + matching account → 201, suggested_account_id заполнен', async () => {
  await seedBank(api, { name: BANK_NAME, extractor_status: 'supported' });
  const user = await setupUserWithMatchingAccount();

  const resp = await uploadFile(api, user.access_token, FIXTURE());
  expect(resp.status()).toBe(201);
  const body = await resp.json();
  expect(body.session_id, 'session created on supported bank').toEqual(expect.any(Number));
  expect(body.suggested_account_id, 'auto-match must surface the seeded account').toEqual(expect.any(Number));
  expect(body.contract_number, 'extractor surfaces contract for the test fixture').toBe(TBANK_CONTRACT);

  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 1.6.2 — Т-Банк pending + matching account → 415 bank_unsupported.
// ---------------------------------------------------------------------------

test('1.6.2 pending bank + matching account → 415 bank_unsupported', async () => {
  await seedBank(api, { name: BANK_NAME, extractor_status: 'pending' });
  const user = await setupUserWithMatchingAccount();

  const resp = await uploadFile(api, user.access_token, FIXTURE());
  expect(resp.status()).toBe(415);
  const body = await resp.json();
  expect(body.code).toBe('bank_unsupported');
  expect(body.bank_id).toBe(bankId);
  expect(body.bank_name).toBe(BANK_NAME);
  expect(body.extractor_status).toBe('pending');

  await cleanupUser(api, user.email);
  await seedBank(api, { name: BANK_NAME, extractor_status: 'supported' }); // proactive restore between tests
});

// ---------------------------------------------------------------------------
// 1.6.3 — Т-Банк in_review + matching account → 415 (status reflects).
//
// `in_review` = parser is in active development. Same gate as `pending`,
// but the field on the response must reflect the actual status so the
// frontend can pick the right copy.
// ---------------------------------------------------------------------------

test('1.6.3 in_review bank + matching account → 415, extractor_status="in_review"', async () => {
  await seedBank(api, { name: BANK_NAME, extractor_status: 'in_review' });
  const user = await setupUserWithMatchingAccount();

  const resp = await uploadFile(api, user.access_token, FIXTURE());
  expect(resp.status()).toBe(415);
  const body = await resp.json();
  expect(body.code).toBe('bank_unsupported');
  expect(body.extractor_status).toBe('in_review');

  await cleanupUser(api, user.email);
  await seedBank(api, { name: BANK_NAME, extractor_status: 'supported' });
});

// ---------------------------------------------------------------------------
// 1.6.4 — Т-Банк broken + matching account → 415 (status="broken").
// ---------------------------------------------------------------------------

test('1.6.4 broken bank + matching account → 415, extractor_status="broken"', async () => {
  await seedBank(api, { name: BANK_NAME, extractor_status: 'broken' });
  const user = await setupUserWithMatchingAccount();

  const resp = await uploadFile(api, user.access_token, FIXTURE());
  expect(resp.status()).toBe(415);
  const body = await resp.json();
  expect(body.code).toBe('bank_unsupported');
  expect(body.extractor_status).toBe('broken');

  await cleanupUser(api, user.email);
  await seedBank(api, { name: BANK_NAME, extractor_status: 'supported' });
});
