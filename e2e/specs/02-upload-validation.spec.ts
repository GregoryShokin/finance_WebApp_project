/**
 * Stage 0.2 — Upload validation (10 scenarios).
 *
 * Tests the backend validator at `app/services/upload_validator.py` plus
 * the global `MaxBodySizeMiddleware`. Every adversarial path returns the
 * correct HTTP status and a structured `code` string:
 *
 *   413 upload_too_large            — per-type cap exceeded (CSV/XLSX 10 MB, PDF 25 MB)
 *   413 global_body_size_exceeded   — middleware Content-Length cap (30 MB)
 *   415 unsupported_upload_type     — magic bytes don't match a known kind
 *   415 empty_file                  — zero-byte upload
 *   415 extension_content_mismatch  — declared extension ≠ detected magic
 *   415 xlsx_decompression_too_large — zip-bomb XLSX (decompresses past 100 MB)
 *
 * Architectural note (KI-01 in docs/E2E_KNOWN_ISSUES.md): the frontend has
 * NO pre-upload validation — every selected file fires the POST regardless
 * of size/extension/content. ТЗ §3.3 expected assertions of "no
 * /imports/upload network request" for 0.2.2-0.2.5; instead these tests
 * assert that the backend correctly rejects the upload. When the frontend
 * gains pre-validation, amend these tests with the network-absence check.
 *
 * Rate limit: /imports/upload is 30/hour per user_or_ip. Tests use unique
 * users (different IDs → different rate buckets), and beforeEach also
 * blanket-resets the upload bucket, so back-to-back runs don't hit 429.
 */
import { test, expect, type APIRequestContext } from '@playwright/test';
import { newApi } from '../helpers/api';
import { cleanupUser, resetRateLimit, seedUser } from '../helpers/seed';
import { uploadBuffer, uploadFile } from '../helpers/upload';
import {
  generateLargeCSVAsync,
  getAdversarialPath,
  getStatementPath,
  getSyntheticPath,
} from '../helpers/files';

let api: APIRequestContext;

test.beforeAll(async () => {
  api = await newApi();
});

test.afterAll(async () => {
  await api.dispose();
});

test.beforeEach(async () => {
  // Upload bucket is `30/hour` per IP — three back-to-back runs would burn it.
  // Reset blanket-wide; the slowapi key is /api/v1/imports/upload.
  await resetRateLimit(api, 'upload');
  await resetRateLimit(api, 'register');
  await resetRateLimit(api, 'login');
});

// ---------------------------------------------------------------------------
// 0.2.1 — Happy path: real Сбер PDF uploads successfully (201).
// ---------------------------------------------------------------------------

test('0.2.1 happy path: загрузка валидного PDF Сбера → 201', async () => {
  const user = await seedUser(api);
  const resp = await uploadFile(api, user.access_token, getStatementPath('Сбер дебет.pdf'));
  expect(resp.status(), `expected 201, body=${await safeBody(resp)}`).toBe(201);
  const body = await resp.json();
  expect(body).toHaveProperty('session_id');
  expect(body).toHaveProperty('source_type', 'pdf');
  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.2.2 — Size cap: PDF > 25 MB → 413 upload_too_large.
//
// KI-01: frontend has no client-side size check, so this exercises the
// streaming size guard in upload_validator.read_upload_with_limits.
// ---------------------------------------------------------------------------

test('0.2.2 PDF > 25 MB cap → 413 upload_too_large', async () => {
  const user = await seedUser(api);
  // Generate a 26 MB PDF on the fly (cached in .tmp/ across runs).
  const largePdf = await Promise.resolve().then(() =>
    require('../helpers/files').generateLargePDF(26),
  );

  const resp = await uploadFile(api, user.access_token, largePdf);
  expect(resp.status()).toBe(413);
  const body = await resp.json();
  expect(body.code).toBe('upload_too_large');
  expect(body.kind).toBe('pdf');
  expect(body.max_size_mb).toBe(25);
  expect(body.actual_size_mb).toBeGreaterThan(25);

  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.2.3 — Wrong extension (.exe) → 415 unsupported_upload_type.
// ---------------------------------------------------------------------------

test('0.2.3 wrong extension (.exe) → 415 unsupported_upload_type', async () => {
  const user = await seedUser(api);
  const resp = await uploadFile(api, user.access_token, getAdversarialPath('fake-extension.exe'));
  expect(resp.status()).toBe(415);
  const body = await resp.json();
  expect(body.code).toBe('unsupported_upload_type');
  // Detail is in Russian — assert a key fragment, not full text (per ТЗ §3.3).
  expect(body.detail).toMatch(/[Нн]е распознан|[Пп]оддерживаются/);
  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.2.4 — Empty file → 415 empty_file.
// ---------------------------------------------------------------------------

test('0.2.4 empty file → 415 empty_file', async () => {
  const user = await seedUser(api);
  const resp = await uploadFile(api, user.access_token, getAdversarialPath('empty.csv'));
  expect(resp.status()).toBe(415);
  const body = await resp.json();
  expect(body.code).toBe('empty_file');
  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.2.5 — Binary content with .csv extension → 415.
//
// Sends raw 0x00 bytes (definitely not CSV: is_plausibly_csv rejects on
// first null byte). With a `.csv` declared extension AND null-byte content,
// the validator reaches detect_magic_kind which returns 'unknown' →
// 415 unsupported_upload_type (it never reaches the extension/magic
// mismatch branch because there's no magic to detect at all).
// ---------------------------------------------------------------------------

test('0.2.5 binary (null bytes) with .csv extension → 415 unsupported_upload_type', async () => {
  const user = await seedUser(api);
  const buf = Buffer.alloc(64); // all zero bytes
  const resp = await uploadBuffer(api, user.access_token, buf, 'binary.csv');
  expect(resp.status()).toBe(415);
  const body = await resp.json();
  expect(body.code).toBe('unsupported_upload_type');
  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.2.6 — Happy path: minimal valid XLSX (synthetic) → 201.
//
// No real anonymized XLSX in Bank-extracts/, so we use scripts/build_minimal_xlsx.py
// output. The validator's xlsx-zip-metadata check passes (manifest has
// xl/workbook.xml, total decompressed < 100 MB). The import service may
// still fail to RECOGNIZE the bank (no extractor matches our synthetic
// header), but that's a 4xx from a different layer; for 0.2.6 we only assert
// validation passed → status < 415 (i.e. backend got past the validator).
// ---------------------------------------------------------------------------

test('0.2.6 minimal valid XLSX проходит валидацию (статус не 415)', async () => {
  const user = await seedUser(api);
  const resp = await uploadFile(api, user.access_token, getSyntheticPath('tiny-valid.xlsx'));
  // Validator-level success means NOT 413/415 with validator codes. Service
  // layer may still 400 (no extractor matches synthetic content), and that's OK
  // for the validator's contract.
  expect(resp.status(), `validator should pass; got ${resp.status()} ${await safeBody(resp)}`).not.toBe(413);
  const body = await safeJson(resp);
  if (resp.status() >= 400) {
    expect(body?.code, 'validator-layer codes must NOT appear when validator passed').not.toBe('upload_too_large');
    expect(body?.code).not.toBe('unsupported_upload_type');
    expect(body?.code).not.toBe('xlsx_decompression_too_large');
    expect(body?.code).not.toBe('xlsx_invalid_archive');
    expect(body?.code).not.toBe('xlsx_missing_manifest');
    expect(body?.code).not.toBe('extension_content_mismatch');
  }
  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.2.7 — extension_content_mismatch: declared .csv, actual PDF magic.
//
// ТЗ §3.2 illustrated this with a `page.evaluate` fetch from a logged-in
// browser. Equivalent (and simpler) via direct upload helper: we wrap the
// PDF magic header bytes in a buffer named `fake.csv`. The validator detects
// 'pdf' from magic, sees declared extension 'csv', emits the mismatch.
// ---------------------------------------------------------------------------

test('0.2.7 extension/content mismatch (PDF bytes in .csv) → 415', async () => {
  const user = await seedUser(api);
  // PDF magic + filler. 5 bytes of magic + ~64 bytes padding so detect_magic_kind
  // has enough to read.
  const buf = Buffer.concat([Buffer.from('%PDF-1.4\n'), Buffer.alloc(64, 0x20)]);
  const resp = await uploadBuffer(api, user.access_token, buf, 'fake.csv', 'text/csv');
  expect(resp.status()).toBe(415);
  const body = await resp.json();
  expect(body.code).toBe('extension_content_mismatch');
  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.2.8 — Zip-bomb XLSX → 415 xlsx_decompression_too_large.
//
// Fixture is 200 MB decompressed but ~205 KB on disk (see
// e2e/scripts/build_zip_bomb.py). Validator's per-type cap (10 MB) doesn't
// fire because the on-disk bytes < 10 MB; the deep-check
// validate_xlsx_zip_metadata catches it via summed file_size from ZipInfo.
// ---------------------------------------------------------------------------

test('0.2.8 zip-bomb XLSX → 415 xlsx_decompression_too_large', async () => {
  const user = await seedUser(api);
  const resp = await uploadFile(api, user.access_token, getAdversarialPath('zip-bomb.xlsx'));
  expect(resp.status()).toBe(415);
  const body = await resp.json();
  expect(body.code).toBe('xlsx_decompression_too_large');
  expect(body.actual_decompressed_mb).toBeGreaterThan(100);
  expect(body.max_decompressed_mb).toBe(100);
  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.2.9 — Middleware cap: body Content-Length > 30 MB → 413 from middleware.
//
// Middleware reads the Content-Length header before the multipart parser.
// We can't lie about Content-Length (Playwright/node sets it from the
// actual body length), so generate an actual 31 MB file. The middleware
// rejects with `code: global_body_size_exceeded`, distinct from the
// per-type validator code, before the request body is parsed.
// ---------------------------------------------------------------------------

test('0.2.9 body > 30 MB → 413 global_body_size_exceeded (middleware)', async () => {
  const user = await seedUser(api);
  const big = await generateLargeCSVAsync(31);
  const resp = await uploadFile(api, user.access_token, big);
  expect(resp.status()).toBe(413);
  const body = await resp.json();
  expect(body.code).toBe('global_body_size_exceeded');
  expect(body.max_size_mb).toBe(30);
  expect(body.actual_size_mb).toBeGreaterThan(30);
  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// 0.2.10 — CP1251 Cyrillic CSV passes validation.
//
// Russian banks emit cp1251-encoded CSVs with high-bit bytes (0xC0-0xFF).
// is_plausibly_csv tolerates b >= 0x80 specifically for this case. We assert
// the validator passes (status < 415 for validator codes); the import
// service may then still fail to detect a bank, but the validator's
// contract is what we test.
// ---------------------------------------------------------------------------

test('0.2.10 CP1251 cyrillic CSV проходит валидацию', async () => {
  const user = await seedUser(api);
  const resp = await uploadFile(api, user.access_token, getAdversarialPath('cyrillic-cp1251.csv'));
  // Same shape as 0.2.6: validator may pass even if recognition fails downstream.
  expect(resp.status()).not.toBe(413);
  const body = await safeJson(resp);
  if (resp.status() >= 400) {
    expect(body?.code).not.toBe('upload_too_large');
    expect(body?.code).not.toBe('unsupported_upload_type');
    expect(body?.code).not.toBe('extension_content_mismatch');
    expect(body?.code).not.toBe('empty_file');
  }
  await cleanupUser(api, user.email);
});

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

async function safeBody(resp: import('@playwright/test').APIResponse): Promise<string> {
  try {
    return (await resp.text()).slice(0, 300);
  } catch {
    return '<unreadable>';
  }
}

async function safeJson(resp: import('@playwright/test').APIResponse): Promise<Record<string, unknown> | null> {
  try {
    return await resp.json() as Record<string, unknown>;
  } catch {
    return null;
  }
}
