/**
 * Stage 0.5 — Duplicate detection on import.
 *
 * Backend contract (app/services/import_service.py:upload_source + ТЗ §3.5):
 *
 *   - First upload of unique bytes → `action_required: null`, fresh session_id.
 *   - Re-upload of identical bytes while previous session is uncommitted
 *     → `action_required: "choose"`, `session_id` points at the EXISTING
 *       session, `existing_progress` populated with row counters.
 *   - Re-upload while ALL prior sessions for that hash are committed
 *     → `action_required: "warn"`, no `existing_progress`.
 *   - `force_new=true` query param bypasses both checks → fresh session
 *     even when a duplicate exists.
 *
 * dedup key is `sha256(raw_bytes)` — filename and Content-Type don't matter.
 * We use the same Сбер debit PDF for all five tests; the bytes are bit-for-
 * bit identical between calls so the hash always matches.
 */
import { test, expect, type APIRequestContext } from '@playwright/test';
import { newApi } from '../helpers/api';
import {
  cleanupUser,
  getImportSessionState,
  markImportSessionCommitted,
  resetRateLimit,
  seedUser,
} from '../helpers/seed';
import { uploadFile } from '../helpers/upload';
import { getStatementPath } from '../helpers/files';
import type { TestUser } from '../helpers/types';

let api: APIRequestContext;
const FIXTURE = () => getStatementPath('Сбер дебет.pdf');

test.beforeAll(async () => {
  api = await newApi();
});

test.afterAll(async () => {
  await api.dispose();
});

test.beforeEach(async () => {
  // Each dedup test creates 2-3 uploads. /imports/upload bucket is 30/hour
  // per user; the new user gets a clean slate, but a global reset costs us
  // nothing and protects against any back-leak from the rate-limit spec.
  await resetRateLimit(api, 'upload');
});

async function uploadFixture(user: TestUser, opts?: { forceNew?: boolean }): Promise<{
  status: number;
  body: Record<string, unknown>;
}> {
  const resp = await uploadFile(api, user.access_token, FIXTURE(), { forceNew: opts?.forceNew });
  return { status: resp.status(), body: await resp.json() };
}

// ---------------------------------------------------------------------------
// 0.5.1 — Fresh upload: action_required=null, new session created.
// ---------------------------------------------------------------------------

test('0.5.1 свежий upload: action_required отсутствует, создана новая сессия', async () => {
  const user = await seedUser(api);

  const first = await uploadFixture(user);
  expect(first.status).toBe(201);
  expect(first.body.action_required, 'fresh upload has no duplicate signal').toBeNull();
  expect(first.body.session_id).toEqual(expect.any(Number));

  // The session is now in a non-committed state and has the file hash recorded.
  const state = await getImportSessionState(api, first.body.session_id as number);
  expect(state.user_id).toBe(user.user_id);
  expect(state.status).not.toBe('committed');
  expect(state.file_hash, 'file_hash must be set on the session').toBeTruthy();
  expect(state.file_hash!.length).toBe(64); // sha256 hex

  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.5.2 — Re-upload while previous session is uncommitted: action_required=CHOOSE.
//
// session_id must point at the EXISTING session (so the frontend can
// `setActive(session_id)` for the "Открыть существующую" button).
// ---------------------------------------------------------------------------

test('0.5.2 повтор того же файла при uncommitted-сессии → action_required="choose"', async () => {
  const user = await seedUser(api);

  const first = await uploadFixture(user);
  expect(first.status).toBe(201);
  const firstSessionId = first.body.session_id as number;

  const second = await uploadFixture(user);
  expect(second.status).toBe(201);
  expect(second.body.action_required).toBe('choose');
  expect(second.body.session_id, 'must point to the EXISTING session').toBe(firstSessionId);
  expect(second.body.existing_progress, 'existing_progress populated for CHOOSE').toBeTruthy();

  // Verify state did not flip — still the same uncommitted session.
  const state = await getImportSessionState(api, firstSessionId);
  expect(state.status).not.toBe('committed');

  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.5.3 — force_new=true bypasses dedup, creates a parallel session.
// ---------------------------------------------------------------------------

test('0.5.3 force_new=true создаёт параллельную сессию, минуя dedup', async () => {
  const user = await seedUser(api);

  const first = await uploadFixture(user);
  const firstSessionId = first.body.session_id as number;

  const second = await uploadFixture(user, { forceNew: true });
  expect(second.status).toBe(201);
  expect(second.body.action_required, 'force_new must skip the duplicate signal').toBeNull();
  expect(second.body.session_id, 'must be a NEW session, not the existing one').not.toBe(firstSessionId);

  // Both sessions exist and share the same file_hash.
  const stateA = await getImportSessionState(api, firstSessionId);
  const stateB = await getImportSessionState(api, second.body.session_id as number);
  expect(stateA.file_hash).toBe(stateB.file_hash);
  expect(stateA.id).not.toBe(stateB.id);

  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.5.4 — existing_progress shape: committed_rows, user_actions, total_rows.
//
// All three fields must be present and non-negative integers. We don't
// assert specific counts — the row-detection step depends on the extractor
// and may evolve; the shape contract is what matters to the frontend modal.
// ---------------------------------------------------------------------------

test('0.5.4 existing_progress содержит committed_rows, user_actions, total_rows', async () => {
  const user = await seedUser(api);

  await uploadFixture(user);
  const second = await uploadFixture(user);
  expect(second.body.action_required).toBe('choose');

  const progress = second.body.existing_progress as {
    committed_rows: number;
    user_actions: number;
    total_rows: number;
  };
  expect(progress).toBeTruthy();
  expect(progress.committed_rows).toEqual(expect.any(Number));
  expect(progress.user_actions).toEqual(expect.any(Number));
  expect(progress.total_rows).toEqual(expect.any(Number));
  expect(progress.committed_rows).toBeGreaterThanOrEqual(0);
  expect(progress.user_actions).toBeGreaterThanOrEqual(0);
  expect(progress.total_rows).toBeGreaterThanOrEqual(0);

  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.5.5 — Re-upload while only COMMITTED sessions exist: action_required=WARN.
//
// ТЗ §3.5 noted that driving the full upload→preview→mapping→commit flow
// through UI is ~10 fragile steps. We instead use /_test/import-session/{id}/
// mark-committed to short-circuit straight to the state the test cares about.
// existing_progress is null on the WARN branch (frontend's soft warning
// banner doesn't need progress counters — there's no work-in-progress to
// preserve).
// ---------------------------------------------------------------------------

test('0.5.5 повтор файла при committed-сессии → action_required="warn"', async () => {
  const user = await seedUser(api);

  const first = await uploadFixture(user);
  const firstSessionId = first.body.session_id as number;

  // Skip the UI commit flow — test endpoint flips status directly.
  const after = await markImportSessionCommitted(api, firstSessionId);
  expect(after.status).toBe('committed');

  const second = await uploadFixture(user);
  expect(second.status).toBe(201);
  expect(second.body.action_required, 'committed-only duplicates yield WARN, not CHOOSE').toBe('warn');
  expect(second.body.existing_progress, 'no existing_progress on WARN').toBeNull();

  await cleanupUser(api, user.email);
});
